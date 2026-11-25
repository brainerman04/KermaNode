"""Official Kerma genesis block used to initialize a fresh node."""

GENESIS_BLOCK = {
    "type": "block",
    "T": "0000abc000000000000000000000000000000000000000000000000000000000",
    "created": 1671062400,
    "miner": "Marabu",
    "nonce": "0" * 58 + "5bb0f2",
    "note": (
        "The New York Times 2022-12-13: Scientists Achieve Nuclear Fusion "
        "Breakthrough With Blast of 192 Lasers"
    ),
    "previd": None,
    "txids": [],
}
