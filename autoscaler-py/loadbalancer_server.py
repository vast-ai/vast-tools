from flask import Flask, request
from loadbalancer import LoadBalancer
import logging

app = Flask(__name__)

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

lb = None

# @app.route("/cold", methods=['POST'])
# def create_cold_set():
#     global lb
#     data = request.json
#     lb = LoadBalancer(cold_set_size=data['cold_set_size'], manage=False)
#     return "Started Cold Set"

@app.route('/setup', methods=['POST'])
def setup_lb():
    global lb
    lb = LoadBalancer()
    return "Started Load Balancer and Autoscaler Session"

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

if __name__ == '__main__':
    app.run(threaded=False, port=5000) #double check multi-threading safety

