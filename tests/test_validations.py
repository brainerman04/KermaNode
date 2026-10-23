from protocol import validate_message, validate_peer_address

print("Validate message:")
print(validate_message({"type": "getpeers"}))

print(validate_message({
    "type": "getpeers",
    "extra": 123
}))

print(validate_message({
    "type": "peers",
    "peers": ["example.org:18018"]
}))

print(validate_message({
    "type": "peers",
    "peers": ["192.168.1.5:18018"]
}))

print("\nValidate peer addresses: ")
print(validate_peer_address("example.org:18018"))
print(validate_peer_address("192.168.1.5:18018"))
print(validate_peer_address("example.org:70000"))
print(validate_peer_address("256.2.3.4:18018"))
print(validate_peer_address("example.org:65535"))
print(validate_peer_address("example.org:65536"))
print(validate_peer_address("example.org:0"))
print(validate_peer_address("node_1.example:18018"))