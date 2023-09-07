import requests
import json
import time
from websockets.sync.client import connect

MSG_END = "$$$"

ooba_dict = {
	'auto_max_new_tokens': False,

	# Generation params. If 'preset' is set to different than 'None', the values
	# in presets/preset-name.yaml are used instead of the individual numbers.
	'preset': 'None',
	'do_sample': True,
	'temperature': 0.7,
	'top_p': 0.1,
	'typical_p': 1,
	'epsilon_cutoff': 0,  # In units of 1e-4
	'eta_cutoff': 0,  # In units of 1e-4
	'tfs': 1,
	'top_a': 0,
	'repetition_penalty': 1.18,
	'repetition_penalty_range': 0,
	'top_k': 40,
	'min_length': 0,
	'no_repeat_ngram_size': 0,
	'num_beams': 1,
	'penalty_alpha': 0,
	'length_penalty': 1,
	'early_stopping': False,
	'mirostat_mode': 0,
	'mirostat_tau': 5,
	'mirostat_eta': 0.1,
	'guidance_scale': 1,
	'negative_prompt': '',

	'seed': -1,
	'add_bos_token': True,
	'truncation_length': 2048,
	'ban_eos_token': False,
	'skip_special_tokens': True,
	'stopping_strings': []
	}

def send_vllm_request(gpu_server_addr, text_prompt):
	URI = f'http://{gpu_server_addr}/generate'
	request_dict = {"prompt" : text_prompt}
	text_result = None
	error = None
	num_tokens = None
	try:
		response = requests.post(URI, json=request_dict)
		if response.status_code == 200:
			reply = response.json()
			if reply["error"] is None:
				text_result = f"{text_prompt} -> {reply['response']}"
				num_tokens = reply["num_tokens"]
			else:
				error = reply['error']
	except requests.exceptions.ConnectionError as e:
		error = f"connection error: {e}"

	return {"reply" : text_result, "error": error, "num_tokens" : num_tokens}

def send_vllm_request_auth(gpu_server_addr, id_token, text_prompt):
	URI = f'http://{gpu_server_addr}/auth'
	model_dict = {"prompt" : text_prompt}
	request_dict = {"token" : id_token, "model" : model_dict}
	text_result = None
	error = None
	num_tokens = None
	try:
		response = requests.post(URI, json=request_dict)
		if response.status_code == 200:
			try:
				reply = response.json()
				if reply["error"] is None:
					text_result = f"{text_prompt} -> {reply['response']}"
					num_tokens = reply["num_tokens"]
				else:
					error = reply['error']
			except json.JSONDecodeError:
				error = "json"
		else:
			error = f"status code: {response.status_code}"
	except requests.exceptions.ConnectionError as e:
		error = f"connection error: {e}"

	return {"reply" : text_result, "error": error, "num_tokens" : num_tokens, "first_msg_wait" : None}

def send_vllm_request_streaming(gpu_server_addr, id_token, text_prompt):
	response = ""
	first_msg_wait = 0.0
	first = True
	with connect(f"ws://{gpu_server_addr}/") as websocket:
		t1 = time.time()
		websocket.send(text_prompt + "?")
		for message in websocket:
			if first:
				t2 = time.time()
				first_msg_wait = t2 - t1
				first = False
			response += message
	return {"reply" : response, "error" : None, "num_tokens" : 50, "first_msg_wait" : first_msg_wait}

def send_vllm_request_streaming_auth(gpu_server_addr, id_token, text_prompt):
	response = ""
	first_msg_wait = 0.0
	first = True
	with connect(f"ws://{gpu_server_addr}/") as websocket:
		websocket.send(id_token)
		websocket.send(MSG_END)

		websocket.send(text_prompt)
		websocket.send(MSG_END)

		t1 = time.time()
		for message in websocket:
			if first:
				t2 = time.time()
				first_msg_wait = t2 - t1
				first = False
			response += message
	return {"reply" : response, "error" : None, "num_tokens" : 50, "first_msg_wait" : first_msg_wait}

def send_vllm_request_streaming_test(gpu_server_addr):
	response = ""
	with connect(f"ws://{gpu_server_addr}/") as websocket:
		websocket.send("Hello?")
		for message in websocket:
			response += message
	# print(response)
	if response != "":
		return True
	else:
		return False

def send_vllm_request_streaming_test_auth(gpu_server_addr, mtoken):
	response = ""
	with connect(f"ws://{gpu_server_addr}/") as websocket:
		websocket.send(mtoken)
		websocket.send(MSG_END)
		websocket.send("Hello?")
		websocket.send(MSG_END)
		for message in websocket:
			response += message
	# print(response)
	if response != "":
		return True
	else:
		return False


def main():
	addr = "31.12.82.146:16100"
	mtoken = "3ee1bbaab030a853dc5b6104ffb0d7b26e0b3a9a7bc790368822bad56dd9c048"
	send_vllm_request_streaming_test_auth(addr, mtoken)

if __name__ == "__main__":
	main()