from protocol import ObjectValidationError
from config import errorType
import re
from copy import deepcopy
import json

# NEU: Für die tatsächliche Ed25519-Signaturprüfung.
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class TransactionValidator:
    def validate(self, transaction, object_store):
        if not isinstance(transaction, dict):
            raise ObjectValidationError(errorType.INV_FORM, "Transaction must be a dictionary")

        if transaction.get("type") != "transaction":
            raise ObjectValidationError(errorType.INV_FORM, "The type must be a transaction")

        is_coinbase = "height" in transaction

        if is_coinbase:
            required_keys = {"type", "height", "outputs"}
        else:
            required_keys = {"type", "inputs", "outputs"}

        if set(transaction.keys()) != required_keys:
            raise ObjectValidationError(errorType.INV_FORM, "Keys do not match")

        if not isinstance(transaction["outputs"], list):
            raise ObjectValidationError(errorType.INV_FORM, "Outputs must be a list")

        required_output_keys = {"pubkey", "value"}
        total_output_value = 0

        for output in transaction["outputs"]:
            if not isinstance(output, dict):
                raise ObjectValidationError(errorType.INV_FORM, "Output must be a dictionary")

            if set(output.keys()) != required_output_keys:
                raise ObjectValidationError(errorType.INV_FORM, "Invalid Output")

            if type(output["value"]) is not int:
                raise ObjectValidationError(errorType.INV_FORM, "Value needs to be an integer")

            if output["value"] < 0:
                raise ObjectValidationError(errorType.INV_FORM, "Value cannot be negative")

            if not isinstance(output["pubkey"], str):
                raise ObjectValidationError(errorType.INV_FORM, "Public key needs to be a string")

            if len(output["pubkey"]) != 64:
                raise ObjectValidationError(errorType.INV_FORM, "Public key must have exactly 64 characters")

            if re.fullmatch(r"[0-9a-f]{64}", output["pubkey"]) is None:
                raise ObjectValidationError(errorType.INV_FORM, "Public key must be hexadecimal")

            total_output_value += output["value"]

        if is_coinbase:
            if type(transaction["height"]) is not int:
                raise ObjectValidationError(errorType.INV_FORM, "Height needs to be an integer")

            return None 
        
        if not isinstance(transaction["inputs"], list):
            raise ObjectValidationError(errorType.INV_FORM, "Inputs must be a list")

        if len(transaction["inputs"]) == 0:
            raise ObjectValidationError(errorType.INV_FORM, "Inputs cannot be empty")

        required_input_keys = {"outpoint", "sig"}
        required_outpoint_keys = {"txid", "index"}
        total_input_value = 0
        seen_outpoints = set()
        verification_inputs = []

        for tx_input in transaction["inputs"]:
            if not isinstance(tx_input, dict):
                raise ObjectValidationError(errorType.INV_FORM, "Input must be a dictionary")

            if set(tx_input.keys()) != required_input_keys:
                raise ObjectValidationError(errorType.INV_FORM, "Invalid Input")

            if not isinstance(tx_input["outpoint"], dict):
                raise ObjectValidationError(errorType.INV_FORM, "Outpoint must be a dictionary")

            if set(tx_input["outpoint"].keys()) != required_outpoint_keys:
                raise ObjectValidationError(errorType.INV_FORM, "Invalid Outpoint")

            if type(tx_input["outpoint"]["index"]) is not int:
                raise ObjectValidationError(errorType.INV_FORM, "Index needs to be an integer")

            if tx_input["outpoint"]["index"] < 0:
                raise ObjectValidationError(errorType.INV_FORM, "Index cannot be negative")

            if not isinstance(tx_input["outpoint"]["txid"], str):
                raise ObjectValidationError(errorType.INV_FORM, "Transaction ID must be a string")

            if len(tx_input["outpoint"]["txid"]) != 64:
                raise ObjectValidationError(errorType.INV_FORM, "Transaction ID must have exactly 64 characters")

            if re.fullmatch(r"[0-9a-f]{64}", tx_input["outpoint"]["txid"]) is None:
                raise ObjectValidationError(errorType.INV_FORM, "Transaction ID must be hexadecimal")

            if not isinstance(tx_input["sig"], str):
                raise ObjectValidationError(errorType.INV_FORM, "Signature must be a string")

            if len(tx_input["sig"]) != 128:
                raise ObjectValidationError(errorType.INV_FORM, "Signature must have exactly 128 characters")

            if re.fullmatch(r"[0-9a-f]{128}", tx_input["sig"]) is None:
                raise ObjectValidationError(errorType.INV_FORM, "Signature must be hexadecimal")

            txid = tx_input["outpoint"]["txid"]
            index = tx_input["outpoint"]["index"]

            current_outpoint = (txid, index)
            if current_outpoint in seen_outpoints:
                raise ObjectValidationError(
                    errorType.INV_TX_CON, "Same outpoint used more than once"
                )
            seen_outpoints.add(current_outpoint)

            referenced_transaction = object_store.get_object(txid)

            if referenced_transaction is None:
                raise ObjectValidationError(errorType.UNKNOWN_OBJ, "Referenced transaction not found")
            
            if not isinstance(referenced_transaction, dict) or referenced_transaction.get("type") != "transaction":
                raise ObjectValidationError(errorType.INV_FORM, "Referenced object is not a transaction")

            if not isinstance(referenced_transaction.get("outputs"), list):
                raise ObjectValidationError(errorType.INV_FORM, "Referenced transaction has invalid outputs")

            if index >= len(referenced_transaction["outputs"]):
                raise ObjectValidationError(errorType.INV_TX_OUT, "Referenced output index does not exist")

            referenced_output = referenced_transaction["outputs"][index]

            if not isinstance(referenced_output, dict) or set(referenced_output.keys()) != required_output_keys:
                raise ObjectValidationError(errorType.INV_FORM, "Referenced output has invalid structure")

            if type(referenced_output["value"]) is not int or referenced_output["value"] < 0:
                raise ObjectValidationError(errorType.INV_FORM, "Referenced output has invalid value")

            if not isinstance(referenced_output["pubkey"], str) or re.fullmatch(r"[0-9a-f]{64}", referenced_output["pubkey"]) is None:
                raise ObjectValidationError(errorType.INV_FORM, "Referenced output has invalid public key")

            input_value = referenced_output["value"]
            referenced_pubkey = referenced_output["pubkey"]
            pubkey_bytes = bytes.fromhex(referenced_pubkey)
            signature_bytes = bytes.fromhex(tx_input["sig"])
            total_input_value += input_value

            verification_inputs.append((pubkey_bytes, signature_bytes))

        if total_output_value > total_input_value:
            raise ObjectValidationError(errorType.INV_TX_CON, "Outputs exceed inputs")

        transaction_copy = deepcopy(transaction)
        for copy_input in transaction_copy["inputs"]:
            copy_input["sig"] = None

        signing_json = json.dumps(transaction_copy, sort_keys=True, separators=(",", ":"))
        signing_bytes = signing_json.encode("utf-8")

        for pubkey_bytes, signature_bytes in verification_inputs:
            try:
                public_key = Ed25519PublicKey.from_public_bytes(pubkey_bytes)
                public_key.verify(signature_bytes, signing_bytes)
            except (InvalidSignature, ValueError) as exc:
                raise ObjectValidationError(
                    errorType.INV_TX_SIG, "Invalid Ed25519 signature"
                ) from exc

        return None
