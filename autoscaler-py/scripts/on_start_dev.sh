env | grep _ >> /etc/environment;
cd /src;
if [ ! -f /root/hasbooted ]
then
    pip install accelerate -U;
    pip install protobuf;
    git clone https://github.com/nickgreenspan/host-server;
    /scripts/docker-entrypoint.sh python3 /app/download-model.py TheBloke/Llama-2-13B-chat-GPTQ --branch gptq-4bit-32g-actorder_True;
fi
touch /root/hasbooted