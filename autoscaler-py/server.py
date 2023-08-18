from flask import Flask, request
from loadbalancer import LoadBalancer


app = Flask(__name__)

lb = None

@app.route("/cold", methods=['POST'])
def create_cold_set():
    global lb
    data = request.json
    lb = LoadBalancer(cold_set_size=data['cold_set_size'], manage=False)
    return "Started Cold Set"


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
    addr = lb.get_next_addr(data["num_tokens"])
    return {"addr" : addr}

@app.route('/metrics', methods=['GET'])
def get_server_metrics():
    global lb
    cost = lb.instance_set.metrics.total_cost
    tps_dict = {}
    for ready_instance in lb.instance_set.ready_instances:
        if "tokens/s" in ready_instance.keys():
            tps_dict[lb.get_address(ready_instance)] = ready_instance["tokens/s"]
        else:
            tps_dict[lb.get_address(ready_instance)] = None
    return {"total_cost" : cost, "reported_tps" : tps_dict}

@app.route('/status', methods=['GET'])
def get_server_status():
    global lb
    return {"num_ready" : len(lb.ready_queue), "num_cold" : len(lb.instance_set.cold_instances), "num_loading" : len(lb.instance_set.loading_instances), "num_hot" : len(lb.instance_set.hot_instances)}



