# install (once)
sudo cp systemd/ppp-transparent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ppp-transparent

# check status and logs
systemctl status ppp-transparent
journalctl -u ppp-transparent -f

# stop/disable
sudo systemctl stop ppp-transparent
sudo systemctl disable ppp-transparent