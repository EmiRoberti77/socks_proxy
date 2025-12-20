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

## flush iptables
sudo iptables -F 

