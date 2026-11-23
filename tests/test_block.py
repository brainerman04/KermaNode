import sys
import unittest
from unittest.mock import patch

from block import BlockValidator
from config import errorType
from object_store import ObjectStore
from protocol import ObjectValidationError
from tests.test_transaction import SIGNED_TRANSACTION

# Offizieller Genesis-Block aus der Protokollbeschreibung. Die Nonce hat 64 Hexzeichen.
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

# Offizieller Block aus Task 3 mit Genesis als Parent und einer Coinbase.
EXAMPLE_BLOCK = {
    "type": "block",
    "T": GENESIS_BLOCK["T"],
    "created": 1671148800,
    "miner": "grader",
    "nonce": "0" * 59 + "463cf",
    "note": "This block has a coinbase transaction",
    "previd": "00002fa163c7dab0991544424b9fd302bb1782b185e5a3bbdf12afb758e57dee",
    "txids": ["6ebfb4c8e8e9b19dcf54c6ce3e1e143da1f473ea986e70c5cb8899a4671c933a"],
}

# Coinbase des Beispielblocks auf Höhe 1 mit 50 Ker zu je 10**12 Picaker.
EXAMPLE_COINBASE = {
    "type": "transaction",
    "height": 1,
    "outputs": [{
        "pubkey": "3f0bc71a375b574e4bda3ddf502fe1afd99aa020bf6049adfe525d9ad18ff33f",
        "value": 50 * 10**12,
    }],
}


class TestBlockValidator(unittest.TestCase):
    def setUp(self):
        # Jeder Test beginnt mit einem eigenen Validator und einem leeren Speicher.
        self.validator = BlockValidator()
        self.store = ObjectStore()

    def assert_invalid_format(self, block):
        # Prüft den Fehlercode für einen einzelnen ungültigen Blockaufbau.
        with self.assertRaises(ObjectValidationError) as caught:
            self.validator.validate_block_format(block)
        self.assertEqual(caught.exception.error_type, errorType.INV_FORM)

    def test_valid_genesis_block(self):
        # Der offizielle Genesis-Block erfüllt Format und Genesis-Regel.
        self.assertIsNone(self.validator.validate_block_format(GENESIS_BLOCK))
        self.assertIsNone(self.validator.validate_genesis(GENESIS_BLOCK))

    def test_valid_example_block(self):
        # Der offizielle Beispielblock erfüllt das Format und hat einen Parent.
        self.assertIsNone(self.validator.validate_block_format(EXAMPLE_BLOCK))
        self.assertIsNone(self.validator.validate_genesis(EXAMPLE_BLOCK))

    def test_optional_fields_may_be_absent_or_use_boundary_values(self):
        # Prüft fehlende Felder, leeren Text und 128 Zeichen mit den ASCII-Grenzen.
        block = {key: value for key, value in EXAMPLE_BLOCK.items() if key not in {"miner", "note"}}
        self.assertIsNone(self.validator.validate_block_format(block))
        block.update(miner="", note=" " + "~" * 127)
        self.assertIsNone(self.validator.validate_block_format(block))

    def test_invalid_keys_or_non_object(self):
        # Prüft fehlende Pflichtschlüssel, zusätzliche Schlüssel und eine Liste als Block.
        missing_previd = dict(EXAMPLE_BLOCK)
        del missing_previd["previd"]
        self.assert_invalid_format(missing_previd)
        self.assert_invalid_format(dict(EXAMPLE_BLOCK, extra=True))
        self.assert_invalid_format([])

    def test_invalid_field_values(self):
        # Ändert pro Subtest genau ein Feld eines gültigen Beispielblocks.
        cases = (
            ("type", " block"),
            ("txids", "a" * 64),
            ("txids", ["a" * 63]),
            ("txids", ["A" * 64]),
            ("nonce", "a" * 64 + "\n"),
            ("previd", "None"),
            ("previd", 0),
            ("created", True),
            ("miner", "ä"),
            ("miner", "x" * 129),
            ("note", "first\nsecond"),
            ("note", None),
            ("T", "0" * 64),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.assert_invalid_format(dict(EXAMPLE_BLOCK, **{field: value}))

    def test_invalid_proof_of_work(self):
        # Die Null-Nonce erzeugt für diesen Beispielblock einen Hash über dem Target.
        block = dict(EXAMPLE_BLOCK, nonce="0" * 64)
        with self.assertRaises(ObjectValidationError) as caught:
            self.validator.validate_proof_of_work(block)
        self.assertEqual(caught.exception.error_type, errorType.INV_BLOCK_POW)

    def test_proof_of_work_accepts_hash_just_below_target(self):
        # Ein vorgegebener Hash prüft T - 1 gezielt. 064x füllt ihn auf 64 Hexzeichen auf.
        target = int(EXAMPLE_BLOCK["T"], 16)
        block_id = f"{target - 1:064x}"
        with patch("block.calculate_objectid", return_value=block_id) as calculate_objectid:
            self.assertIsNone(self.validator.validate_proof_of_work(EXAMPLE_BLOCK))
        calculate_objectid.assert_called_once_with(EXAMPLE_BLOCK)

    def test_proof_of_work_rejects_hash_at_or_above_target(self):
        # Prüft die strikte Obergrenze anhand der vorgegebenen Hashes T und T + 1.
        target = int(EXAMPLE_BLOCK["T"], 16)
        for block_id_value in (target, target + 1):
            with self.subTest(offset=block_id_value - target):
                block_id = f"{block_id_value:064x}"
                with patch("block.calculate_objectid", return_value=block_id):
                    with self.assertRaises(ObjectValidationError) as caught:
                        self.validator.validate_proof_of_work(EXAMPLE_BLOCK)
                self.assertEqual(caught.exception.error_type, errorType.INV_BLOCK_POW)

    def test_invalid_genesis_block_validation(self):
        # Die geänderte Nonce ergibt eine andere ID, obwohl previd weiterhin null ist.
        block = dict(GENESIS_BLOCK, nonce="0" * 64)
        with self.assertRaises(ObjectValidationError) as caught:
            self.validator.validate_genesis(block)
        self.assertEqual(caught.exception.error_type, errorType.INV_GEN)
        self.assertEqual(caught.exception.error_type.value, "INVALID_GENESIS")

    def test_resolve_parent_returns_none_for_genesis(self):
        # Für Genesis ist None der erwartete Rückgabewert.
        parent = self.validator.resolve_parent(GENESIS_BLOCK, self.store)
        self.assertIsNone(parent)

    def test_resolve_parent_returns_stored_genesis(self):
        # Der Parent des Beispielblocks wird über seine ID im Speicher gefunden.
        self.store.add_object(GENESIS_BLOCK)
        parent = self.validator.resolve_parent(EXAMPLE_BLOCK, self.store)
        self.assertEqual(parent, GENESIS_BLOCK)

    def test_resolve_parent_rejects_unknown_parent(self):
        # In einem leeren Speicher kann der Parent des Beispielblocks nicht gefunden werden.
        with self.assertRaises(ObjectValidationError) as caught:
            self.validator.resolve_parent(EXAMPLE_BLOCK, self.store)
        self.assertEqual(caught.exception.error_type, errorType.UNKNOWN_OBJ)

    def test_resolve_parent_rejects_transaction_as_parent(self):
        # Eine vorhandene Objekt-ID genügt nur, wenn das Objekt ein Block ist.
        transaction = {
            "type": "transaction",
            "height": 1,
            "outputs": [{"pubkey": "a" * 64, "value": 50 * 10**12}],
        }
        txid = self.store.add_object(transaction)
        block = dict(EXAMPLE_BLOCK, previd=txid)
        with self.assertRaises(ObjectValidationError) as caught:
            self.validator.resolve_parent(block, self.store)
        self.assertEqual(caught.exception.error_type, errorType.INV_FORM)

    def test_timestamp_accepts_after_parent_through_current_time(self):
        # Zehn Sekunden Abstand zur Testuhr lassen Platz für beide gültigen Grenzen.
        parent_time = GENESIS_BLOCK["created"]
        now = parent_time + 10
        with patch("block.time.time", return_value=now):
            for created in (parent_time + 1, now):
                with self.subTest(created=created):
                    block = dict(EXAMPLE_BLOCK, created=created)
                    self.assertIsNone(self.validator.validate_timestamp(block, GENESIS_BLOCK))

    def test_timestamp_rejects_before_or_equal_to_parent(self):
        # Ein Block muss strikt neuer als sein Parent sein. Gleiche Zeiten sind ungültig.
        parent_time = GENESIS_BLOCK["created"]
        now = parent_time + 10
        with patch("block.time.time", return_value=now):
            for created in (parent_time - 1, parent_time):
                with self.subTest(created=created):
                    block = dict(EXAMPLE_BLOCK, created=created)
                    with self.assertRaises(ObjectValidationError) as caught:
                        self.validator.validate_timestamp(block, GENESIS_BLOCK)
                    self.assertEqual(caught.exception.error_type, errorType.INV_BLOCK_TS)

    def test_timestamp_rejects_future_time(self):
        # Eine Sekunde nach der fest vorgegebenen Testuhr reicht für eine Ablehnung.
        now = GENESIS_BLOCK["created"] + 10
        block = dict(EXAMPLE_BLOCK, created=now + 1)
        with patch("block.time.time", return_value=now):
            with self.assertRaises(ObjectValidationError) as caught:
                self.validator.validate_timestamp(block, GENESIS_BLOCK)
        self.assertEqual(caught.exception.error_type, errorType.INV_BLOCK_TS)

    def test_calculate_block_height_for_genesis(self):
        # Genesis liegt auf Höhe 0 und braucht keinen gespeicherten Parent.
        self.assertEqual(self.validator.calculate_block_height(GENESIS_BLOCK, self.store), 0)

    def test_calculate_block_height_for_example_block(self):
        # Der direkte Nachfolger von Genesis liegt auf Höhe 1.
        self.store.add_object(GENESIS_BLOCK)
        self.assertEqual(self.validator.calculate_block_height(EXAMPLE_BLOCK, self.store), 1)

    def test_calculate_block_height_with_two_ancestors(self):
        # Zwei Parent-Verweise bis Genesis ergeben Höhe 2.
        self.store.add_object(GENESIS_BLOCK)
        example_id = self.store.add_object(EXAMPLE_BLOCK)
        child = dict(EXAMPLE_BLOCK, previd=example_id)
        self.assertEqual(self.validator.calculate_block_height(child, self.store), 2)

    def test_calculate_block_height_rejects_missing_ancestor(self):
        # Der direkte Parent ist vorhanden, sein eigener Parent fehlt im Speicher.
        example_id = self.store.add_object(EXAMPLE_BLOCK)
        child = dict(EXAMPLE_BLOCK, previd=example_id)
        with self.assertRaises(ObjectValidationError) as caught:
            self.validator.calculate_block_height(child, self.store)
        self.assertEqual(caught.exception.error_type, errorType.UNKNOWN_OBJ)

    def test_calculate_block_height_rejects_invalid_genesis_ancestor(self):
        # Ein veränderter Genesis-Block ist auch als gespeicherter Vorfahr ungültig.
        invalid_genesis = dict(GENESIS_BLOCK, note="Different genesis")
        invalid_genesis_id = self.store.add_object(invalid_genesis)
        child = dict(EXAMPLE_BLOCK, previd=invalid_genesis_id)
        with self.assertRaises(ObjectValidationError) as caught:
            self.validator.calculate_block_height(child, self.store)
        self.assertEqual(caught.exception.error_type, errorType.INV_GEN)

    def test_calculate_block_height_above_recursion_limit(self):
        # Zehn Blöcke über dem Python-Rekursionslimit sichern die Schleife gegen eine Regression ab.
        expected_height = sys.getrecursionlimit() + 10
        block = GENESIS_BLOCK
        for height in range(1, expected_height + 1):
            parent_id = self.store.add_object(block)
            block = dict(EXAMPLE_BLOCK, previd=parent_id, created=GENESIS_BLOCK["created"] + height)

        self.assertEqual(self.validator.calculate_block_height(block, self.store), expected_height)

    def test_validate_block_coinbase_accepts_block_without_coinbase(self):
        # Die Coinbase ist bei leerer Liste und bei regulären Transaktionen optional.
        for transactions in ([], [SIGNED_TRANSACTION]):
            with self.subTest(transaction_count=len(transactions)):
                coinbase = self.validator.validate_block_coinbase(transactions, 1, self.store)
                self.assertIsNone(coinbase)

    def test_validate_block_coinbase_returns_coinbase_at_index_zero(self):
        # Eine Coinbase auf passender Höhe muss an erster Position zurückgegeben werden.
        transactions = [EXAMPLE_COINBASE, SIGNED_TRANSACTION]
        coinbase = self.validator.validate_block_coinbase(transactions, 1, self.store)
        self.assertIs(coinbase, EXAMPLE_COINBASE)

    def test_validate_block_coinbase_rejects_coinbase_at_later_index(self):
        # Eine reguläre Transaktion vor der Coinbase verletzt die Positionsregel.
        transactions = [SIGNED_TRANSACTION, EXAMPLE_COINBASE]
        with self.assertRaises(ObjectValidationError) as caught:
            self.validator.validate_block_coinbase(transactions, 1, self.store)
        self.assertEqual(caught.exception.error_type, errorType.INV_BLOCK_CB)
        self.assertIn("found at index 1", caught.exception.explanation)

    def test_validate_block_coinbase_rejects_second_coinbase(self):
        # Auch nach einer gültigen Coinbase an erster Position ist eine weitere verboten.
        transactions = [EXAMPLE_COINBASE, SIGNED_TRANSACTION, EXAMPLE_COINBASE]
        with self.assertRaises(ObjectValidationError) as caught:
            self.validator.validate_block_coinbase(transactions, 1, self.store)
        self.assertEqual(caught.exception.error_type, errorType.INV_BLOCK_CB)
        self.assertIn("more than one coinbase transaction", caught.exception.explanation)

    def test_validate_block_coinbase_rejects_wrong_output_count(self):
        # Prüft beide Seiten der Regel, dass eine Coinbase genau einen Output hat.
        for output_count in (0, 2):
            with self.subTest(output_count=output_count):
                coinbase = dict(EXAMPLE_COINBASE, outputs=EXAMPLE_COINBASE["outputs"] * output_count)
                with self.assertRaises(ObjectValidationError) as caught:
                    self.validator.validate_block_coinbase([coinbase], 1, self.store)
                self.assertEqual(caught.exception.error_type, errorType.INV_FORM)
                self.assertIn(f"exactly one output, found {output_count}", caught.exception.explanation)

    def test_validate_block_coinbase_rejects_malformed_transaction(self):
        # Prüft die weitergereichten Formatfehler für Inputs, Höhe und Public Key.
        for changes in ({"inputs": []}, {"height": True}, {"outputs": [{"pubkey": "bad", "value": 1}]}):
            with self.subTest(changes=changes):
                coinbase = dict(EXAMPLE_COINBASE, **changes)
                with self.assertRaises(ObjectValidationError) as caught:
                    self.validator.validate_block_coinbase([coinbase], 1, self.store)
                self.assertEqual(caught.exception.error_type, errorType.INV_FORM)

    def test_validate_block_coinbase_rejects_height_mismatch(self):
        # Die Coinbase auf Höhe 1 gehört nicht in einen Block auf Höhe 2.
        with self.assertRaises(ObjectValidationError) as caught:
            self.validator.validate_block_coinbase([EXAMPLE_COINBASE], 2, self.store)
        self.assertEqual(caught.exception.error_type, errorType.INV_BLOCK_CB)
        self.assertIn("Coinbase height 1 does not match block height 2", caught.exception.explanation)

    def test_validate_coinbase_reward_accepts_block_without_coinbase(self):
        # Bei fehlender Coinbase gibt es keinen Auszahlungsbetrag zu prüfen.
        self.assertIsNone(self.validator.validate_coinbase_reward(None, total_fees=0))

    def test_validate_coinbase_reward_accepts_value_at_or_below_limit(self):
        # PERSON2: Feste Testgebühren ersetzen hier die Summe aus der Transaktionsausführung.
        # Sieben Picaker erlauben Auszahlungen von sechs und genau sieben Picaker über dem Basisreward.
        base_reward = EXAMPLE_COINBASE["outputs"][0]["value"]
        for total_fees, claimed_fees in ((0, 0), (7, 6), (7, 7)):
            with self.subTest(total_fees=total_fees, claimed_fees=claimed_fees):
                output = dict(EXAMPLE_COINBASE["outputs"][0], value=base_reward + claimed_fees)
                coinbase = dict(EXAMPLE_COINBASE, outputs=[output])
                self.assertIsNone(self.validator.validate_coinbase_reward(coinbase, total_fees))

    def test_validate_coinbase_reward_rejects_value_one_picaker_above_limit(self):
        # Ein Picaker über der Obergrenze reicht für INVALID_BLOCK_COINBASE.
        total_fees = 7
        max_reward = EXAMPLE_COINBASE["outputs"][0]["value"] + total_fees
        output = dict(EXAMPLE_COINBASE["outputs"][0], value=max_reward + 1)
        coinbase = dict(EXAMPLE_COINBASE, outputs=[output])
        with self.assertRaises(ObjectValidationError) as caught:
            self.validator.validate_coinbase_reward(coinbase, total_fees)
        self.assertEqual(caught.exception.error_type, errorType.INV_BLOCK_CB)
        self.assertIn(str(output["value"]), caught.exception.explanation)
        self.assertIn(str(max_reward), caught.exception.explanation)
