import unittest
import tempfile
import json
from copy import deepcopy
from utxo import execute_block
from object_hash import calculate_objectid
from protocol import ObjectValidationError
from config import errorType
from pathlib import Path
from object_store import ObjectStore
from config import GEN_BLOCK_ID

from test_transaction import (
    COINBASE,
    COINBASE_ID,
    SIGNED_TRANSACTION,
    FakeObjectStore
)

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat
)

class TestUTXO(unittest.TestCase):

    def setUp(self):
        self.store = FakeObjectStore()

        self.parent_utxo = {
            (COINBASE_ID, 0): deepcopy(
                COINBASE["outputs"][0]
            )
        }
        self.private_key = Ed25519PrivateKey.generate()

        self.public_key = self.private_key.public_key().public_bytes(
            Encoding.Raw,
            PublicFormat.Raw
        ).hex()

        self.test_coinbase_tx = {
            "type": "transaction",
            "height": 1,
            "outputs": [
                {
                    "pubkey": self.public_key,
                    "value": 50000000000000
                }
            ]
        }

        self.test_coinbase_id = calculate_objectid(
            self.test_coinbase_tx
        )

        self.store.objects[self.test_coinbase_id] = (
            self.test_coinbase_tx
        )

        self.test_parent_utxo = {
            (self.test_coinbase_id, 0):
                deepcopy(self.test_coinbase_tx["outputs"][0])
        }

    def test_empty_block(self):
        new_utxo, fees = execute_block(
            {}, [], None, self.store
        )

        self.assertEqual(new_utxo, {})
        self.assertEqual(fees, 0)

    def test_coinbase(self):
        new_utxo, fees = execute_block(
            {},
            [COINBASE],
            COINBASE_ID,
            self.store
        )

        self.assertEqual(new_utxo, self.parent_utxo)
        self.assertEqual(fees, 0)

    def test_valid_transaction(self):
        tx = deepcopy(SIGNED_TRANSACTION)
        txid = calculate_objectid(tx)

        new_utxo, fees = execute_block(
            self.parent_utxo,
            [tx],
            None,
            self.store
        )

        self.assertNotIn(
            (COINBASE_ID, 0), new_utxo
        )

        self.assertEqual(
            new_utxo[(txid, 0)],
            tx["outputs"][0]
        )

        self.assertEqual(
            new_utxo[(txid, 1)],
            tx["outputs"][1]
        )

        self.assertEqual(len(new_utxo), 2)
        self.assertEqual(fees, 0)

    def test_double_spending(self):
        with self.assertRaises(ObjectValidationError) as caught:
            execute_block(
                self.parent_utxo,
                [
                    deepcopy(SIGNED_TRANSACTION),
                    deepcopy(SIGNED_TRANSACTION)
                ],
                None,
                self.store
            )

        self.assertEqual(
            caught.exception.error_type,
            errorType.INV_TX_OUT
        )

    def test_unconfirmed_output(self):
        with self.assertRaises(ObjectValidationError) as caught:
            execute_block(
                {},
                [deepcopy(SIGNED_TRANSACTION)],
                None,
                self.store
            )

        self.assertEqual(
            caught.exception.error_type,
            errorType.INV_TX_OUT
        )

    def test_same_block_coinbase_spending(self):
        with self.assertRaises(ObjectValidationError) as caught:
            execute_block(
                {},
                [
                    deepcopy(COINBASE),
                    deepcopy(SIGNED_TRANSACTION)
                ],
                COINBASE_ID,
                self.store
            )

        self.assertEqual(
            caught.exception.error_type,
            errorType.INV_TX_OUT
        )

    def test_parent_unchanged(self):
        original = deepcopy(self.parent_utxo)

        execute_block(
            self.parent_utxo,
            [deepcopy(SIGNED_TRANSACTION)],
            None,
            self.store
        )

        self.assertEqual(self.parent_utxo, original)

    def test_invalid_block_unchanged(self):
        original = deepcopy(self.parent_utxo)

        with self.assertRaises(ObjectValidationError):
            execute_block(
                self.parent_utxo,
                [
                    deepcopy(SIGNED_TRANSACTION),
                    deepcopy(SIGNED_TRANSACTION)
                ],
                None,
                self.store
            )

        self.assertEqual(self.parent_utxo, original)

    def test_forks(self):
        original = deepcopy(self.parent_utxo)

        fork_a, _ = execute_block(
            self.parent_utxo,
            [deepcopy(SIGNED_TRANSACTION)],
            None,
            self.store
        )

        fork_b, _ = execute_block(
            self.parent_utxo,
            [],
            None,
            self.store
        )

        self.assertNotEqual(fork_a, fork_b)
        self.assertEqual(fork_b, original)
        self.assertEqual(self.parent_utxo, original)

    def test_example_coinbase(self):
        coinbase = {
            "height": 1,
            "outputs": [
                {
                    "pubkey": "3f0bc71a375b574e4bda3ddf502fe1afd99aa020bf6049adfe525d9ad18ff33f",
                    "value": 50000000000000
                }
            ],
            "type": "transaction"
        }

        txid = calculate_objectid(coinbase)

        self.assertEqual(
            txid,
            "6ebfb4c8e8e9b19dcf54c6ce3e1e143da1f473ea986e70c5cb8899a4671c933a"
        )

        new_utxo, fees = execute_block(
            {}, [coinbase], txid, self.store
        )

        self.assertEqual(
            new_utxo,
            {(txid, 0): coinbase["outputs"][0]}
        )

        self.assertEqual(fees, 0)

    def test_genesis_utxo(self):
        store = ObjectStore()

        self.assertEqual(
            store.get_utxo(GEN_BLOCK_ID),
            {}
        )

    def test_utxo_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "objects.json")

            store = ObjectStore(path)

            store.set_utxo(
                "test_block",
                self.parent_utxo
            )

            store.save()

            loaded_store = ObjectStore(path)
            loaded_store.load()

            self.assertEqual(
                loaded_store.get_utxo("test_block"),
                self.parent_utxo
            )

            self.assertEqual(
                loaded_store.get_utxo(GEN_BLOCK_ID),
                {}
            )

    def test_utxo_copy(self):
        store = ObjectStore()

        store.set_utxo(
            "test_block",
            self.parent_utxo
        )

        retrieved_utxo = store.get_utxo("test_block")
        retrieved_utxo.clear()

        self.assertEqual(
            store.get_utxo("test_block"),
            self.parent_utxo
        )

    @staticmethod
    def create_signed_transaction(private_key, txid, index, outputs):
        transaction = {
            "type": "transaction",
            "inputs": [
                {
                    "outpoint": {
                        "txid": txid,
                        "index": index
                    },
                    "sig": None
                }
            ],
            "outputs": outputs
        }

        signing_bytes = json.dumps(
            transaction,
            sort_keys=True,
            separators=(",", ":")
        ).encode("utf-8")

        signature = private_key.sign(signing_bytes)

        transaction["inputs"][0]["sig"] = signature.hex()

        return transaction
    
    def test_positive_fees(self):
        tx = self.create_signed_transaction(
            self.private_key,
            self.test_coinbase_id,
            0,
            [
                {
                    "pubkey": self.public_key,
                    "value": 49000000000000
                }
            ]
        )

        new_utxo, fees = execute_block(
            self.test_parent_utxo,
            [tx],
            None,
            self.store
        )

        self.assertEqual(fees, 1000000000000)

    def create_transaction_chain(self):
        tx1 = self.create_signed_transaction(
            self.private_key,
            self.test_coinbase_id,
            0,
            [{
                "pubkey": self.public_key,
                "value": 49000000000000
            }]
        )

        tx1_id = calculate_objectid(tx1)
        self.store.objects[tx1_id] = tx1

        tx2 = self.create_signed_transaction(
            self.private_key,
            tx1_id,
            0,
            [{
                "pubkey": self.public_key,
                "value": 47000000000000
            }]
        )

        tx2_id = calculate_objectid(tx2)
        self.store.objects[tx2_id] = tx2

        return tx1, tx2

    def test_intra_block_spending(self):
        tx1, tx2 = self.create_transaction_chain()

        new_utxo, fees = execute_block(
            self.test_parent_utxo,
            [tx1, tx2],
            None,
            self.store
        )

        tx2_id = calculate_objectid(tx2)

        self.assertEqual(
            new_utxo,
            {(tx2_id, 0): tx2["outputs"][0]}
        )

        self.assertEqual(fees, 3000000000000)

    def test_invalid_transaction_order(self):
        tx1, tx2 = self.create_transaction_chain()

        with self.assertRaises(ObjectValidationError) as caught:
            execute_block(
                self.test_parent_utxo,
                [tx2, tx1],
                None,
                self.store
            )

        self.assertEqual(
            caught.exception.error_type,
            errorType.INV_TX_OUT
        )

class TestUTXOStorage(unittest.IsolatedAsyncioTestCase):

    async def test_save_validated_block(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "objects.json")

            store = ObjectStore(path)

            block = {
                "type": "block",
                "previd": GEN_BLOCK_ID,
                "txids": [COINBASE_ID]
            }

            utxo = {
                (COINBASE_ID, 0): deepcopy(
                    COINBASE["outputs"][0]
                )
            }

            blockid = await store.add_validated_block(
                block, utxo
            )

            self.assertEqual(
                store.get_object(blockid), block
            )

            self.assertEqual(
                store.get_utxo(blockid), utxo
            )

            loaded_store = ObjectStore(path)
            loaded_store.load()

            self.assertEqual(
                loaded_store.get_object(blockid), block
            )

            self.assertEqual(
                loaded_store.get_utxo(blockid), utxo
            )
            
if __name__ == "__main__":
    unittest.main()