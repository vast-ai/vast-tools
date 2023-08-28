env | grep _ >> /etc/environment;
cd /src;
if [ ! -f /root/hasbooted ]
then
    pip install accelerate -U;
    pip install protobuf;
    git clone https://github.com/nickgreenspan/host-server;
    /scripts/docker-entrypoint.sh python3 /app/download-model.py meta-llama/Llama-2-13b-hf;
fi
touch /root/hasbooted
python3 /src/host-server/model_inference_server.py