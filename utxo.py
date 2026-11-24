from copy import deepcopy
from transaction import TransactionValidator
from protocol import ObjectValidationError
from config import errorType
from object_hash import calculate_objectid

def execute_block(parent_utxo, transactions, coinbase_txid, object_store):

    utxo = deepcopy(parent_utxo)
    total_fees = 0

    for transaction in transactions:
        txid = calculate_objectid(transaction)
        if txid == coinbase_txid:
            for index, output in enumerate(transaction["outputs"]):
                utxo[(txid, index)] = deepcopy(output)

            continue

        fee = execute_transaction(
            utxo,
            transaction,
            coinbase_txid,
            object_store
        )

        total_fees += fee

    return utxo, total_fees

def execute_transaction(utxo, transaction, coinbase_txid, object_store):

    validator = TransactionValidator()
    validator.validate(transaction, object_store)

    txid = calculate_objectid(transaction)

    total_input_value = 0
    total_output_value = 0
    spent_outpoints = set()

    for tx_input in transaction["inputs"]:
        outpoint = tx_input["outpoint"]

        key = (outpoint["txid"], outpoint["index"])

        if outpoint["txid"] == coinbase_txid:
            raise ObjectValidationError(
                errorType.INV_TX_OUT,
                "Cannot spend coinbase in the same block"
            )

        if key not in utxo or key in spent_outpoints:
            raise ObjectValidationError(
                errorType.INV_TX_OUT,
                "Output is not in the UTXO set"
            )

        total_input_value += utxo[key]["value"]
        spent_outpoints.add(key)

        for output in transaction["outputs"]:
            total_output_value += output["value"]

        fee = total_input_value - total_output_value

        for key in spent_outpoints:
            del utxo[key]

        for index, output in enumerate(transaction["outputs"]):
            utxo[(txid, index)] = deepcopy(output)

        return fee    