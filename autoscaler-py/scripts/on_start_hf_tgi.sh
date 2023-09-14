env | grep _ >> /etc/environment;
if [ ! -f /root/hasbooted ]
then
    pip install flask
    git clone https://github.com/nickgreenspan/host-server;
    touch ~/.no_auto_tmux
    touch /root/hasbooted
fi
cd /usr/src/host-server
source start_server.sh