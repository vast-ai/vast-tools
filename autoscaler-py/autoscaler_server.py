from flask import Flask, request
from autoscaler import InstanceSet
import logging

app = Flask(__name__)

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

autoscaler = None

@app.route("/setup", methods=['POST'])
def setup_autoscaler():
    global autoscaler
    data = request.json
    autoscaler = InstanceSet(**data["args"])
    return "Started InstanceSet"

@app.route("/destroy", methods=['POST'])
def destroy_autoscaler():
    global autoscaler
    autoscaler.deconstruct()
    return "Destroyed InstanceSet"

@app.route("/hot", methods=["GET"])
def get_hot_instances():
    global autoscaler
    autoscaler.lock.acquire()
    hot_list = autoscaler.hot_instances
    autoscaler.lock.release()
    return {"hot_instances" : hot_list}

@app.route("/report",methods=['POST'])
def report_hot_busy():
    global autoscaler
    data = request.json
    autoscaler.lock.acquire()
    autoscaler.num_hot = data["num_hot"]
    autoscaler.num_busy = data["num_busy"]
    autoscaler.lock.release()
    return "Updated num_hot and num_busy"

@app.route('/metrics', methods=['GET'])
def get_server_metrics():
    global autoscaler
    autoscaler.metrics.lock.acquire()
    cost = autoscaler.metrics.total_cost
    autoscaler.metrics.lock.release()
    tps_dict = {}
    # for hot_instance in autoscaler.hot_instances:
    #     if "tokens/s" in hot_instance.keys():
    #         tps_dict[get_address(hot_instance)] = hot_instance["tokens/s"]
    #     else:
    #         tps_dict[get_address(hot_instance)] = None
    return {"total_cost" : cost, "reported_tps" : tps_dict}

@app.route('/status', methods=['GET'])
def get_server_status():
    global autoscaler
    autoscaler.lock.acquire()
    status = {"num_hot" : autoscaler.num_hot, "num_cold" : len(autoscaler.cold_instances), "num_image_loading" : len(autoscaler.loading_instances), "num_model_loading" : len(autoscaler.hot_instances) - autoscaler.num_hot}
    autoscaler.lock.release()
    return status

@app.route('/gpu_report_hot', methods=['POST'])
def gpu_report_hot():
    pass

if __name__ == '__main__':
    app.run(threaded=False, port=8000) #think about how to support multi-threading safety



