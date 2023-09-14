from flask import Flask, request
from autoscaler import InstanceSet
import logging
import subprocess
import re
import time

app = Flask(__name__)

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

autoscaler = None

def get_cloudflared_link():
    process = subprocess.Popen([f"cloudflared tunnel --url http://localhost:8000"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    tee_process = subprocess.Popen(
        "tee -a cloudflare.log",
        shell=True,
        stdin=process.stderr,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True 
    )
    http_pattern = r'https://[a-zA-Z0-9-]+\.trycloudflare\.com'
    url = None
    for line in tee_process.stdout:
        http_match = re.search(http_pattern, line)
        if http_match:
            url = http_match.group()
            break
    if url:
        return url + '/gpureport'

@app.route("/setup", methods=['POST'])
def setup_autoscaler():
    global autoscaler
    data = request.json
    print("getting link")
    cloudflare_addr=get_cloudflared_link()
    print(f"got link: {cloudflare_addr}")
    autoscaler = InstanceSet(**data["args"], cloudflare_addr=cloudflare_addr)
    return "Started InstanceSet'n"

@app.route("/destroy", methods=['POST'])
def destroy_autoscaler():
    global autoscaler
    autoscaler.deconstruct()
    return "Destroyed InstanceSet\n"

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

# Old version for VLLM
# @app.route('/gpureport', methods=['POST'])
# def gpu_report_hot():
#     global autoscaler
#     data = request.json
#     instance_id = data["id"]
#     print(f"[autoscaler_server] recieved message from id: {instance_id}")

#     # need locks here?
#     model_info = autoscaler.instance_info_map[instance_id]
#     if not(model_info["model_loaded"]) and "loaded" in data.keys() and data["loaded"]:
#         model_info["model_loaded"] = True
#         print("[autoscaler_server] model loaded")

#     if "tokens/s" in data.keys():
#         if data["tokens/s"] >= 1.0: #could use an average system in the future
#             model_info["tokens/s"] = data["tokens/s"]
#             print("[autoscaler_server] updated tokens/s")

#     if "num_running" in data.keys():
#         model_info["num_running"] = data["num_running"]
#         print("[autoscaler_server] updated num_running")

#     return "Updated model info"

# Different version for HF TGI
@app.route('/gpureport', methods=['POST'])
def gpu_report_hot():
    global autoscaler
    data = request.json
    instance_id = data["id"]
    print(f"[autoscaler_server] recieved message from id: {instance_id}")

    model_info = autoscaler.instance_info_map[instance_id]
    if "loaded" in data.keys() and data["loaded"]:
        model_info["model_loaded"] = True #model loaded is then the model files have finished downloading to the instance
        model_info["hot"] = True #hot is when the model is in memory
        print("[autoscaler_server] model loaded and hot")

    if "time_per_token" in data.keys():
        model_info["tokens/s"] = 1 / data["time_per_token"]
        model_info["tokens"] += (model_info["tokens/s"] * data["inference_time"])

    return "Updated model info"

if __name__ == '__main__':
    app.run(threaded=False, port=8000) #think about how to support multi-threading safety



