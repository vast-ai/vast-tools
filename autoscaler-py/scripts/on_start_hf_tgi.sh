env | grep _ >> /etc/environment;
if [ ! -f /root/hasbooted ]
then
    pip install flask
    mkdir /home/workspace
    cd /home/workspace
    git clone https://github.com/nickgreenspan/host-server;
    touch ~/.no_auto_tmux
    touch /root/hasbooted
fi
cd /home/workspace/host-server
source start_server.sh