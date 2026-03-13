# Rueckgrat
ai chat frontend &amp; backend

# get started

For a full install launch install.sh
In case you only want to install specific parts launch install.sh inside the folders infrastructure, backend or chat
To make everything work you need at least one of each.

To launch the chat:
cd chat
./run.sh

# example chat.conf

expected at: ~/.config/Rueckgrat/chat.conf

[General]
backend_port=443
backend_host=192.168.1.111
server_cert="/var/www/html/rueckgrad_backend.crt"
 
# example infrastructure.json

expected at: ~/.config/Rueckgrat/infrastructure.json

Contains list of infrastructure servers. Each node works as a cache for the model registry.
The first server in the list offer a llama.cpp service

```
{
  "servers": [
    {
      "host": "localhost",
      "port": 7346,
      "services": [
        {
          "type": "llm",
          "name": "Rueckgrat_llama.cpp",
          "port": 8080
        }
      ]
    },
    {
      "host": "192.168.2.158",
      "port": 7346
    }    
  ]
}
```
