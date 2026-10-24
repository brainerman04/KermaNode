import asyncio
from peer_manager import PeerManager


async def main():
    manager = PeerManager()

    for i in range(50):
        manager.add_peers([f"node{i}.example.org:18018"])

    print(len(manager.get_peers()))


asyncio.run(main())