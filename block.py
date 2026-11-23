import re
import time

from object_hash import calculate_objectid

from config import errorType, GEN_BLOCK_ID
from protocol import ObjectValidationError
from transaction import TransactionValidator


# Festes Mining-Target aus der Kerma-Protokollbeschreibung (Abschnitt 3.2).
BLOCK_TARGET = "0000abc000000000000000000000000000000000000000000000000000000000"


def _is_hex32(value: object) -> bool:
    """Prüft Hexwerte mit 32 Bytes. Jedes Byte braucht zwei Hexzeichen."""
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


class BlockValidator:
    """Prüft Kerma-Blöcke und ihre Coinbase unabhängig vom Netzwerk."""

    def validate_block_format(self, block: object) -> None:
        """Prüft die erlaubten Felder, ihre Datentypen und das feste Target."""
        required_keys = {"type", "txids", "nonce", "previd", "created", "T"}
        optional_keys = {"miner", "note"}

        if not isinstance(block, dict):
            explanation = "Block must be a dictionary"
        elif required_keys - set(block):
            missing_keys = ", ".join(sorted(required_keys - set(block)))
            explanation = f"Block is missing required fields: {missing_keys}."
        elif set(block) - required_keys - optional_keys:
            explanation = "Block must only contain type, txids, nonce, previd, created and T; only miner and note as additional fields are allowed."
        elif not isinstance(block["type"], str) or block["type"] != "block":
            explanation = "Block type must be 'block'."
        elif not isinstance(block["txids"], list):
            explanation = "Block txids must be a list."
        elif not all(_is_hex32(txid) for txid in block["txids"]):
            explanation = "All txids must be 64-character lowercase hexadecimal strings."
        elif not _is_hex32(block["nonce"]):
            explanation = "Block nonce must be a 64-character lowercase hexadecimal string."
        elif block["previd"] is not None and not _is_hex32(block["previd"]):
            explanation = "Block previd must be null or a 64-character lowercase hexadecimal string."
        # Die strikte Typprüfung schließt Python-Bools als Unix-Zeitstempel aus.
        elif type(block["created"]) is not int:
            explanation = "Block created must be an integer."
        elif block["T"] != BLOCK_TARGET:
            explanation = "Block T must equal the required mining target."
        else:
            for field in ("miner", "note"):
                if field not in block:
                    continue
                value = block[field]
                # Kerma erlaubt bis zu 128 druckbare ASCII-Zeichen (0x20 bis 0x7E).
                if (
                    not isinstance(value, str)
                    or len(value) > 128
                    or not all(0x20 <= ord(char) <= 0x7E for char in value)
                ):
                    raise ObjectValidationError(
                        errorType.INV_FORM,
                        f"Block {field} must contain at most 128 printable ASCII characters.",
                    )
            return

        raise ObjectValidationError(errorType.INV_FORM, explanation)

    def validate_proof_of_work(self, block: dict) -> None:
        """Prüft, ob der Hash des vollständigen Blocks strikt unter dem Target liegt."""
        blockID = calculate_objectid(block)
        # Block-ID und Target sind Hexzahlen. Basis 16 ergibt ihre numerischen Werte.
        BLOCK_TARGET_INT = int(BLOCK_TARGET, 16)
        blockID_INT = int(blockID, 16)
        if blockID_INT >= BLOCK_TARGET_INT:
            raise ObjectValidationError(
                errorType.INV_BLOCK_POW,
                f"Block proof of work is invalid: {blockID} is not less than {BLOCK_TARGET}.",
            )

    def validate_genesis(self, block: dict) -> None:
        """Erlaubt einen Block ohne Parent nur mit der offiziellen Genesis-ID."""
        if block["previd"] is not None:
            return

        block_id = calculate_objectid(block)
        if block_id != GEN_BLOCK_ID:
            raise ObjectValidationError(
                errorType.INV_GEN,
                f"Genesis block ID is invalid: {block_id} does not match expected {GEN_BLOCK_ID}.",
            )

    def resolve_parent(self, block: dict, object_store: object):
        """Lädt den direkten Parent aus dem Objektspeicher und prüft seinen Typ."""
        if block["previd"] is None:
            return None

        parent_block = object_store.get_object(block["previd"])
        if parent_block is None:
            raise ObjectValidationError(
                errorType.UNKNOWN_OBJ,
                f"Parent block {block['previd']} not found in object store.",
            )
        if not isinstance(parent_block, dict) or parent_block.get("type") != "block":
            raise ObjectValidationError(
                errorType.INV_FORM,
                f"Parent object {block['previd']} is not a valid block.",
            )

        return parent_block

    def validate_timestamp(self, block: dict, parent: dict) -> None:
        """Prüft Unix-Sekunden gegen die aktuelle Zeit und den direkten Parent."""
        timestamp = time.time()
        if(block["created"] > timestamp):
            raise ObjectValidationError(
                errorType.INV_BLOCK_TS,
                f"Block timestamp {block['created']} is in the future (current time: {timestamp}).",
            )
        if parent is None:
            return

        if block["created"] <= parent["created"]:
            raise ObjectValidationError(
                errorType.INV_BLOCK_TS,
                f"Block timestamp {block['created']} is not greater than parent block timestamp {parent['created']}.",
            )

    def calculate_block_height(self, block: dict, object_store: object) -> int:
        """Zählt die Parent-Verweise bis zum offiziellen Genesis-Block."""
        current_block = block
        # Genesis hat Höhe 0. Jeder Parent-Verweis erhöht den Abstand um eins.
        height = 0
        while current_block["previd"] is not None:
            current_block = self.resolve_parent(current_block, object_store)
            height += 1

        self.validate_genesis(current_block)
        return height

    def validate_block_coinbase(self, transactions, block_height, object_store):
        """Prüft Anzahl, Position, Format und Höhe der Coinbase und gibt sie zurück."""
        coinbase = None
        # Die Eingabereihenfolge entspricht txids. Das Feld height kennzeichnet die Coinbase.
        for index, transaction in enumerate(transactions):
            if "height" not in transaction:
                continue
            if coinbase is not None:
                raise ObjectValidationError(
                    errorType.INV_BLOCK_CB,
                    "Block contains more than one coinbase transaction.",
                )
            if index != 0:
                raise ObjectValidationError(
                    errorType.INV_BLOCK_CB,
                    f"Coinbase transaction must be at index 0, found at index {index}.",
                )
            coinbase = transaction

        if coinbase is None:
            return None

        # Den Aufbau der Transaktion prüft Task 2. Task 3 verlangt genau einen Output.
        TransactionValidator().validate(coinbase, object_store)
        output_count = len(coinbase["outputs"])
        if output_count != 1:
            raise ObjectValidationError(
                errorType.INV_FORM,
                f"Coinbase transaction must have exactly one output, found {output_count}.",
            )

        coinbase_height = coinbase["height"]
        if coinbase_height != block_height:
            raise ObjectValidationError(
                errorType.INV_BLOCK_CB,
                f"Coinbase height {coinbase_height} does not match block height {block_height}.",
            )

        # PERSON2: Diese Coinbase bei der Gebührensumme der regulären Transaktionen auslassen.
        return coinbase

    def validate_coinbase_reward(self, coinbase, total_fees):
        """Prüft den Auszahlungsbetrag einer bereits validierten Coinbase."""
        # PERSON2: total_fees ist die Summe (Inputs minus Outputs) der erfolgreich
        # ausgeführten regulären Transaktionen dieses Blocks als Integer in Picaker.
        if coinbase is None:
            return

        # Kerma sieht 50 Ker Basisreward vor. Ein Ker entspricht 10**12 Picaker.
        # Die Gebührensumme in derselben Einheit erhöht den maximalen Reward.
        upper_bound = 50 * 10**12 + total_fees
        output_value = coinbase["outputs"][0]["value"]
        if output_value > upper_bound:
            raise ObjectValidationError(
                errorType.INV_BLOCK_CB, 
                f"Output value {output_value} exceeded upper bound {upper_bound}.",
            )
        
