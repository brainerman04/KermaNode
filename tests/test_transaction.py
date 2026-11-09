import copy
import unittest

from config import errorType
from protocol import ObjectValidationError
from transaction import TransactionValidator


COINBASE_ID = "d46d09138f0251edc32e28f1a744cb0b7286850e4c9c777d7e3c6e459b289347"
COINBASE = {
    "height": 0,
    "outputs": [{"pubkey": "85acb336a150b16a9c6c8c27a4e9c479d9f99060a7945df0bb1b53365e98969b", "value": 50000000000000}],
    "type": "transaction",
}

# Offizielles gültiges Task-2-Beispiel.
SIGNED_TRANSACTION = {
    "inputs": [{
        "outpoint": {"index": 0, "txid": COINBASE_ID},
        "sig": "6204bbab1b736ce2133c4ea43aff3767c49c881ac80b57ba38a3bab980466644cdbacc86b1f4357cfe45e6374b963f5455f26df0a86338310df33e50c15d7f04",
    }],
    "outputs": [
        {"pubkey": "b539258e808b3e3354b9776d1ff4146b52282e864f56224e7e33e7932ec72985", "value": 10},
        {"pubkey": "8dbcd2401c89c04d6e53c81c90aa0b551cc8fc47c0469217c8f5cfbae1e911f9", "value": 49999999999990},
    ],
    "type": "transaction",
}


class FakeObjectStore:
    def __init__(self, objects=None):
        self.objects = objects if objects is not None else {COINBASE_ID: copy.deepcopy(COINBASE)}

    def get_object(self, objectid):
        return self.objects.get(objectid)


class TestTransactionValidator(unittest.TestCase):
    def setUp(self):
        self.validator = TransactionValidator()
        self.store = FakeObjectStore()

    def expect_error(self, tx, expected_type, store=None):
        with self.assertRaises(ObjectValidationError) as caught:
            self.validator.validate(tx, self.store if store is None else store)
        self.assertEqual(caught.exception.error_type, expected_type)

    def test_valid_coinbase(self):
        self.assertIsNone(self.validator.validate(copy.deepcopy(COINBASE), self.store))

    def test_valid_signed_transaction_and_no_mutation(self):
        tx = copy.deepcopy(SIGNED_TRANSACTION)
        before = copy.deepcopy(tx)
        self.assertIsNone(self.validator.validate(tx, self.store))
        self.assertEqual(tx, before)

    def test_invalid_signature(self):
        tx = copy.deepcopy(SIGNED_TRANSACTION)
        tx["outputs"][0]["pubkey"] = "a" + tx["outputs"][0]["pubkey"][1:]
        self.expect_error(tx, errorType.INV_TX_SIG)

    def test_bad_signature_format(self):
        tx = copy.deepcopy(SIGNED_TRANSACTION)
        tx["inputs"][0]["sig"] = "z" * 128
        self.expect_error(tx, errorType.INV_FORM)

    def test_missing_reference(self):
        self.expect_error(copy.deepcopy(SIGNED_TRANSACTION), errorType.UNKNOWN_OBJ, FakeObjectStore({}))

    def test_missing_output_index(self):
        tx = copy.deepcopy(SIGNED_TRANSACTION)
        tx["inputs"][0]["outpoint"]["index"] = 1
        self.expect_error(tx, errorType.INV_TX_OUT)

    def test_duplicate_input_outpoint(self):
        tx = copy.deepcopy(SIGNED_TRANSACTION)
        tx["inputs"].append(copy.deepcopy(tx["inputs"][0]))
        self.expect_error(tx, errorType.INV_TX_CON)

    def test_conservation(self):
        tx = copy.deepcopy(SIGNED_TRANSACTION)
        tx["outputs"][0]["value"] += 1
        self.expect_error(tx, errorType.INV_TX_CON)

    def test_empty_inputs(self):
        tx = copy.deepcopy(SIGNED_TRANSACTION)
        tx["inputs"] = []
        self.expect_error(tx, errorType.INV_FORM)

    def test_output_boolean_not_integer(self):
        tx = copy.deepcopy(SIGNED_TRANSACTION)
        tx["outputs"][0]["value"] = True
        self.expect_error(tx, errorType.INV_FORM)

    def test_input_boolean_index_not_integer(self):
        tx = copy.deepcopy(SIGNED_TRANSACTION)
        tx["inputs"][0]["outpoint"]["index"] = True
        self.expect_error(tx, errorType.INV_FORM)

    def test_invalid_referenced_object_type(self):
        self.expect_error(copy.deepcopy(SIGNED_TRANSACTION), errorType.INV_FORM, FakeObjectStore({COINBASE_ID: {"type": "block"}}))

    def test_invalid_transaction_type(self):
        self.expect_error({"type": "block", "outputs": []}, errorType.INV_FORM)

    def test_negative_coinbase_height_is_not_semantically_checked_in_task2(self):
        tx = copy.deepcopy(COINBASE)
        tx["height"] = -1
        self.assertIsNone(self.validator.validate(tx, self.store))

    def test_malformed_input_not_crash(self):
        tx = copy.deepcopy(SIGNED_TRANSACTION)
        tx["inputs"] = [5]
        self.expect_error(tx, errorType.INV_FORM)

    def test_malformed_referenced_output_not_crash(self):
        stored = copy.deepcopy(COINBASE)
        stored["outputs"] = [None]
        self.expect_error(copy.deepcopy(SIGNED_TRANSACTION), errorType.INV_FORM, FakeObjectStore({COINBASE_ID: stored}))


if __name__ == "__main__":
    unittest.main()
