from flask import Flask, jsonify, request, current_app, render_template
from functools import wraps
from random import randint
from datetime import datetime, timedelta
from collections import OrderedDict
import numpy as np
import time
import boto3
try:
	import baker
except Exception,e:
	return str(e)

## the core flask app
app = Flask(__name__)



@app.route("/")
def template_index():
	try:
		return render_template('index.html')
	except Exception, e:
		return "Error:"+str(e)

@app.route("/bake")
def bake():
	try:
		return jsonify("hello")
		#return jsonify(baker.bake_emr())
	except Exception, e:
		return str(e)
				
@app.route('/pull/<table_name>')
def pull(table_name):
	try:
		client = boto3.client('sdb')
		paginator = client.get_paginator('select')
		output = {}
		query = "select * from {}".format(table_name)
		response = paginator.paginate( SelectExpression=query, ConsistentRead=True )
		for r in response:
			for i,row in enumerate(r['Items']):
				output[str(row['Name'])] = row['Attributes']
		return jsonify(output)
	except Exception, e:
		return str(e)+'error'

@app.route('/checkcluster')
def check_cluster_status():
	try:
		client = boto3.client('emr')

		# this is a little shaky, as there may be >1 clusters running in production
		# maybe better to search by cluster name as well?
		clusters = client.list_clusters(ClusterStates=['RUNNING','WAITING','BOOTSTRAPPING'])['Clusters']

		if len(clusters) > 0:

			cstatus = clusters[0]['Status']['State']
			cname   = clusters[0]['Name']
			return jsonify({"name":cname,"status":cstatus})
		else:
			return "No active clusters found"+cstatus+" "+cname
	except Exception, e:
		return str(e)+cstatus
## verify: verify that a user has followed us on instagram/twitter; if so, register them in 'usernames' table
## we need the support_jsonp decorator to return JSONP format to Qualtrics - otherwise it throws a CORS error
#@app.route('/verify/<medium>/<username>/<followed>/<unique_id>', methods = ['GET'])
#@support_jsonp
#def verify(medium, username, followed, unique_id):


## run flask
if __name__ == '__main__':
	app.run(host='127.0.0.1',port=12340, debug = True)

## setting default values for optional paths:
## http://stackoverflow.com/questions/14032066/flask-optional-url-parameters
