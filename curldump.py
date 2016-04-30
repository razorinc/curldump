from flask import Flask, request, send_file, Response, render_template, make_response
import datetime
import hashlib
import os
import json
import uuid
import magic
import sqlite3
import random
import StringIO
import string

from openstack import connection
conn = None

if os.environ.get("OS_AUTH_URL"):
    conn = connection.Connection(auth_url=os.environ["OS_AUTH_URL"],
                                 project_name=os.environ["OS_TENANT_NAME"],
                                 username=os.environ["OS_USERNAME"],
                                 password=os.environ["OS_PASSWORD"])
else:
    conn = connection.Connection(auth_url="http://packstack:5000/v2.0",
                                 project_name="demo",
                                 username="demo",
                                 password="redhat")


BASE_URL="https://curldu.mp/"
SHORTLEN=10
SHORTLIFETIME=-30

CONTAINER="curldumper"

application = Flask(__name__)
application.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 # Maximum filesize is 10MB

@application.route("/", methods=['GET'])
def curldump():
    r = make_response(render_template("index.md"))
    r.headers["Content-Type"] = "text/plain"
    return r

@application.route("/", methods=['POST'])
def postfile():
    rv = []
    for file in request.files.itervalues():
        h = savefile(file.filename, file.stream)
        rv.append(BASE_URL+h+"\n")

    return Response("".join(rv), mimetype="text/uri-list")

# Shortener
@application.route("/s/<fileid>", methods=['GET'])
def getshort(fileid):
    if (len(fileid) == SHORTLEN) and (fileid.isalnum() == True):
        c = sqlite3.connect("short.db")
        cur = c.cursor()
        cur.execute("SELECT h FROM short WHERE s='%s'" % fileid)
        for row in cur:
            return getfile(row[0])
    return Response("File not found.\n", mimetype="text/plain", status=404)

@application.route("/<fileid>", methods=['GET'])
def getfile(fileid):
    attach = False

    if (request.args.has_key("attach")):
        attach = True
    try:
        requested_file = conn.object_store.get_object_metadata(fileid, container=CONTAINER)
    except:
        return Response("File not found.\n", mimetype="text/plain", status=404)
    print requested_file.metadata['original-filename']
    try:
        if (requested_file.metadata.has_key("auth")):
            if (checkauth(requested_file.metadata["auth"]) == False):
                raise

        strIO = StringIO.StringIO()
        strIO.write(conn.object_store.get_object(requested_file))
        strIO.seek(0)
        return send_file(strIO,
                         attachment_filename=requested_file.metadata["original-filename"],
                         as_attachment=attach)

    except:
        return Response("You have to login to access this file", 401, {"WWW-Authenticate": "Basic realm='Login Required'"})

@application.route("/<filename>", methods=['PUT'])
def putfile(filename):
    h = savefile(filename, request.stream)
    return Response(BASE_URL+h+"\n", mimetype="text/uri-list")

@application.route("/", methods=['PUT'])
def putstream():
    filename = str(uuid.uuid4())
    h = savefile(filename, request.stream)
    return Response(BASE_URL+h+"\n", mimetype="text/uri-list")

def checkauth(auth):
    if (request.authorization):
        if (auth == hashlib.sha512(request.authorization["username"]+request.authorization["password"]).hexdigest()):
            return True
    return False

def savefile(filename, s):

    now = datetime.datetime.now().isoformat()
    h = hashlib.sha1(""+now+filename).hexdigest()
    container = conn.object_store.get_container_metadata(CONTAINER)
    uploaded_file = conn.object_store.upload_object(container=container,
                                            name=h,
                                            data=s.read())
    conn.object_store.set_object_metadata(uploaded_file, original_filename=filename)

    if (request.authorization):
        auth_credentials = hashlib.sha512(request.authorization["username"]+
                              request.authorization["password"]).hexdigest()
        conn.object_store.set_object_metadata(uploaded_file, auth = auth_credentials)

    if (request.headers.get("X-SHORT")):
        return shortened(uploaded_file.name)

    return h

def shortened(h):
    s = "".join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(SHORTLEN))
    c = sqlite3.connect("short.db")
    c.execute("DELETE FROM short WHERE dt < ?", (datetime.datetime.now()+datetime.timedelta(days=SHORTLIFETIME),))
    c.execute("INSERT INTO short(s, h, dt) VALUES(?, ?, ?)", (s, h, datetime.datetime.now()))
    c.commit()
    c.close()
    return "s/"+s

if __name__ == "__main__":
    application.run(host='::1')
