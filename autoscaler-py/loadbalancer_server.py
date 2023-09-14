from flask import Flask, Response, request 
from loadbalancer import LoadBalancer
import logging
from prompt_model import hf_tgi_streaming_auth_generator

app = Flask(__name__)

# log = logging.getLogger('werkzeug')
# log.setLevel(logging.ERROR)

lb = None

@app.route('/setup', methods=['POST'])
def setup_lb():
	global lb
	args = request.json["args"]
	print(args)
	lb = LoadBalancer(args)
	return "Started Load Balancer and Autoscaler Session\n"

@app.route('/destroy', methods=['POST'])
def destroy_lb():
	global lb
	if lb is not None:
		data = request.json
		lb.deconstruct(kill_servers=data["kill_servers"])
		lb = None
		return "Stopped Load Balancer and Autoscaler Session"
	else:
		return "Load Balancer hasn't been initialized"

@app.route('/connect', methods=['GET'])
def get_connection():
	global lb
	data = request.json
	addr, token = lb.get_next_addr(data["num_tokens"])
	return {"addr" : addr, "token": token}

@app.route('/generate_stream', methods=['POST'])
def prompt_stream():
	global lb
	data = request.json
	addr, token = lb.get_next_addr(data["parameters"]["max_new_tokens"])
	return Response(hf_tgi_streaming_auth_generator(addr, token, data["inputs"], data["parameters"]))

if __name__ == '__main__':
	app.run(threaded=False, port=5000) #double check multi-threading safety

