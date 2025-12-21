## list iptables
sudo iptables -L

## DROP packets from 104.154.249.83
sudo iptables -I INPUT -s 104.154.249.83 -j DROP
## DROP packets from 104.154.249.83 entire subnet
sudo iptables -I INPUT -s 104.154.249.83/24 -j DROP
## REJECT packets from 104.154.249.83
sudo iptables -I INPUT -s 104.154.249.83 -j REJECT
## ALLOW packets from 104.154.249.83
sudo iptables -I INPUT -s 104.154.249.83 -j ACCEPY
## REDIRECT LOCAL TRAFFIC FROM 8081 -> 8080
sudo iptables -t nat -A PREROUTING -p tcp --dport 8081 -j REDIRECT --to-port 8080
sudo iptables -t nat -I OUTPUT 1 -p tcp --dport 8081 -j REDIRECT --to-ports 8080
## get the lines you want to delete
sudo iptables -t nat -L PREROUTING --line-numbers
## delete a rule
sudo iptables -t nat -D PREROUTING 2

# flush just OUTPUT in nat for a clean test (temporary)
sudo iptables -t nat -F OUTPUT
## show atcive connection
ss -tnp | grep -E '104\.154\.249\.83:8891|:8891
ss -tnp | grep -E ':8891|:7978|104\.154\.249\.83|172\.23\.16\.1' || true
## save rules to iptables
sudo /sbin/iptables-save

## windows port foreward into WSL
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8891 connectaddress=172.23.16.1 connectport=8891

netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8891 connectaddress=172.23.23.15 connectport=8891

netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=7978 connectaddress=172.23.23.15 connectport=7978

## delete them from windows
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=8891

netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=7979

## show port proxy is setup
netsh interface portproxy show v4tov4
## flush iptables
sudo iptables -F 


# delete the destination-specific rule (line numbers can change; safer to match by spec)
sudo iptables -t nat -D PPP_PROXY -p tcp -d 172.23.16.1 --dport 7978 -j REDIRECT --to-ports 6767
# add a generic port redirect
sudo iptables -t nat -I PPP_PROXY 5 -p tcp --dport 7978 -j REDIRECT --to-ports 6767



sudo iptables -t nat -F OUTPUT

# Don’t touch PPP itself or loopback
sudo iptables -t nat -A OUTPUT -p tcp --dport 6767 -j RETURN
sudo iptables -t nat -A OUTPUT -p tcp -d 127.0.0.0/8 -j RETURN

# Don’t intercept PPP -> DCS
sudo iptables -t nat -A OUTPUT -p tcp -d 192.168.1.188 --dport 1081 -j RETURN

# Intercept the CCS/VSG gateway target
sudo iptables -t nat -A OUTPUT -p tcp -d 192.168.1.109 --dport 7978 -j REDIRECT --to-ports 6767

# Optional: intercept cloud endpoint
sudo iptables -t nat -A OUTPUT -p tcp -d 104.154.249.83 --dport 8891 -j REDIRECT --to-ports 6767

# clear old rules
sudo conntrack -D -p tcp -d 192.168.1.109 --dport 7978
sudo conntrack -D -p tcp -d 192.168.1.188 --dport 1081


[Windows CCS]
192.168.1.109:7978
        ↑
        │ (normal LAN TCP)
        │
[Linux VM running DCS]
192.168.1.X:1081
        ↑
        │ SOCKS5
        │
[WSL PPP]
172.23.x.x → 6767

# clear old setting
sudo iptables -t nat -F OUTPUT
# Do NOT redirect PPP itself
sudo iptables -t nat -A OUTPUT -p tcp --dport 6767 -j RETURN

# Do NOT redirect DCS
sudo iptables -t nat -A OUTPUT -p tcp -d 192.168.32.128 --dport 1081 -j RETURN

# Redirect telemetry
sudo iptables -t nat -A OUTPUT \
    -p tcp -d 104.154.249.83 --dport 8891 \
    -j REDIRECT --to-ports 6767

# Force dummy video destination into PPP
sudo iptables -t nat -A OUTPUT \
  -p tcp -d 198.18.0.1 --dport 7979 \
  -j REDIRECT --to-ports 6767

sudo iptables -t nat -A OUTPUT \
  -p tcp -d 198.18.0.1 --dport 8000 \
  -j REDIRECT --to-ports 6767
# Verify
sudo iptables -t nat -L OUTPUT -n -v


