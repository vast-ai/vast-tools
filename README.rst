Install Dependencies
==================
To install all required dependencies, run::

    pip install -r requirements.txt

Vast CLI Setup
=============
In order to allow the autoscaler script to create and destroy instances, you need to set up the Vast CLI, which can be achieved by completing the 'PyPI Install' and 'Quickstart' sections of this guide: https://vast.ai/docs/cli/quickstart

Overview
========
There are three main components of the autoscaler-py repo, which are the autoscaler, the loadbalancer, and the sim. The autoscaler and the loadbalancer both have flask webserver interfaces, which are defined in autoscaler_server.py and loadbalancer_server.py respectively. 

autoscaler.py
============
The main logic of the autoscaler is found in autoscaler.py, and the main object is the InstanceSet. The InstanceSet represents a set of Vast.ai instances, all of which are categorized into different states. A "running" instance is an instance that has completely loaded its docker image, and can be accessed with ssh. The "hot" instances are a subset of the "running" instances, and have the model fully downloaded to them, and are ready to start serving requests from clients. There are periodic checks on the "running" instances to see if they are "hot" which include checking the logs of the instance, and sending the model server on the instance a test prompt to see if it is able to return an output. The communication between the model server and the autoscaler is something that could be optimized in the future, by having the model server send messages to the autoscaler directly.

management logic
--------------
To manage the starting and stopping, and creation and deletion of instances, the code uses the concept of a "busy" instance to measure the amount of traffic the InstanceSet is currently experiencing, and make management decisions accordingly. It takes a long time for the model to load onto the instances (for the non-quantized 70B llama model it takes upwards of an hour), so it is recommended to start from a set of instances that already have the model loaded on them, and are currently turned stopped but ready to be started.

loadbalancer.py
=============
The loadbalancer is what the client interfaces with to get the address of the next server to send their request to. Client requests are not sent to the loadbalancer, which ensures their privacy. The loadbalancer reciecieves the set of "hot" instances from the autoscaler, and maintains a PriorityQueue of "hot" instances, ordered by the amount of work they have been given. The loadbalancer calculates the average amount of work across all "hot" instances, and compares that to the average workload a model server can handle, and uses this to report the number of "busy" instances back to the autoscaler.

authorization
-----------
Since clients are interacting directly with the model servers, we need a way to ensure that the client sending a request to it is authorized to do so. To do this, we use "authorization tokens". As part of the code running on the remote instance to serve the model is the "auth_server". The loadbalancer interacts with the "auth_server" using the code in instance_client.py. The auth_server will generate a batch of auth_tokens, send those back to the loadbalancer, and then for every model server address the loadbalancer sends to a client, it will send with it an auth_token, which the model server will check before taking the prompt set by the client. The loadbalancer uses a "Master token" to authenticate with the auth_server (this is generated at the time of instance creation) so that bad actors are unable to get authorization tokens from the server themselves. Periodically the loadbalancer will ping the auth_server for more tokens, when its current stock is running low. 

sim.py
======
This is the driver code which runs a simulation of clients concurrently interacting with the loadbalancer/autoscaler and then sending prompt requests to the set of model_server instances. 

Relevant parameters
-----------------
* num_iterations: The number of rounds of user requests that are sent to the set of instances
* base_num_users: The number of concurrent users (each has a probability of generating a request)
* streaming: Streaming allows the response from the model to be sent back to the client as it is being generated, instead of waiting for the whole response to be generated before sending it back to the client all at once.
* manage: Whether or not the autoscaler should start and stop instances according to its management logic, or if you want to keep your set of instances fixed.
* model: The model that should be loaded on the instances that you create. Currently supports "vllm-13" or "vllm-70"

How to run a simulation
=====================
I recommend opening three different terminal windows so that the output from each component is separate and easily readable. One should run::

    python autoscaler_server.py

to start the autoscaler, the second should run::

    python loadbalancer_server.py

to start the loadbalancer, and the third should run::

    python sim.py

to start the sim.

Once the simulation is complete, the sim window will print out performance and cost metrics for your simulation session.
