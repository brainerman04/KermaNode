"""Task 3: network-independent coordination of block validation and fetching.

The network module supplies callbacks for sending errors, gossip, and accessing
currently handshaken peers. No changes to the Task 2 public method signatures
are required.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable

from block import BlockValidator
from config import errorType
from object_hash import calculate_objectid
from protocol import ObjectValidationError, sendMessage
from utxo import execute_block

log = logging.getLogger(__name__)


@dataclass
class PendingBlock:
    block: dict
    sender: object
    missing: set[str]
    timer: asyncio.Task | None = field(default=None)


class BlockProcessor:
    """Connects BlockValidator, UTXO execution, storage, and network messages."""

    def __init__(self, object_store, broadcast, send_error, peer_writers: Callable):
        self.store = object_store
        self.validator = BlockValidator()
        self.broadcast = broadcast
        self.send_error = send_error
        self.peer_writers = peer_writers
        self.pending: dict[str, PendingBlock] = {}
        self.processing: set[str] = set()
        self.background_tasks: set[asyncio.Task] = set()

    @staticmethod
    def _keep_connection(error_type) -> bool:
        return error_type in (errorType.UNKNOWN_OBJ, errorType.UNFINDABLE_OBJ)

    async def _report(self, writer, error_type, explanation: str) -> bool:
        await self.send_error(writer, error_type, explanation)
        return self._keep_connection(error_type)

    def _check_base(self, block: dict) -> None:
        """Reject invalid blocks before requesting any transactions."""
        self.validator.validate_block_format(block)
        self.validator.validate_genesis(block)
        self.validator.validate_proof_of_work(block)
        parent = self.validator.resolve_parent(block, self.store)
        self.validator.validate_timestamp(block, parent)
        self.validator.calculate_block_height(block, self.store)
        if parent is not None and self.store.get_utxo(block["previd"]) is None:
            raise ObjectValidationError(errorType.INV_ANC,"Parent block has no validated UTXO state.",)

    async def receive_block(self, block: dict, writer) -> bool:
        """Accept or reject a block; pending blocks do NOT block the peer reader."""
        blockid = calculate_objectid(block)
        if (self.store.has_object(blockid) or blockid in self.pending or blockid in self.processing):
            return True
        try:
            self._check_base(block)
        except ObjectValidationError as exc:
            return await self._report(writer, exc.error_type, exc.explanation)

        missing = {txid for txid in block["txids"]
                   if not self.store.has_object(txid)}
        if not missing:
            return await self._finalize(block, writer)

        pending = PendingBlock(block=block, sender=writer, missing=missing)
        self.pending[blockid] = pending
        pending.timer = asyncio.create_task(
            self._expire_after_five_seconds(blockid),
            name=f"block-timeout:{blockid[:12]}",
        )
        await self._request_transactions(missing, writer)
        return True

    async def _request_transactions(self, txids: set[str], sender) -> None:
        """Ask the original sender and other handshaken peers for every missing tx."""
        writers = [sender, *self.peer_writers()]
        distinct_writers = list(dict.fromkeys(writers))
        async def request_one(writer, txid):
            try:
                await sendMessage(writer, {"type": "getobject", "objectid": txid})
            except (OSError, TimeoutError, RuntimeError):
                log.warning("Could not request transaction %s from peer", txid)

        await asyncio.gather(*(
            request_one(writer, txid)
            for txid in sorted(txids)
            for writer in distinct_writers
        ))

    async def _expire_after_five_seconds(self, blockid: str) -> None:
        try:
            await asyncio.sleep(5)
            pending = self.pending.pop(blockid, None)
            if pending is not None:
                await self.send_error(
                    pending.sender,
                    errorType.UNFINDABLE_OBJ,
                    f"Transactions still missing for block {blockid}: "
                    + ", ".join(sorted(pending.missing)),
                )
        except asyncio.CancelledError:
            return

    def transaction_received(self, txid: str) -> None:
        """Resume each block whose last missing transaction has just arrived."""
        for blockid, pending in list(self.pending.items()):
            pending.missing.discard(txid)
            if pending.missing:
                continue
            self.pending.pop(blockid, None)
            if pending.timer is not None:
                pending.timer.cancel()
            task = asyncio.create_task(
                self._finalize(pending.block, pending.sender),
                name=f"finish-block:{blockid[:12]}",
            )
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)

    async def transaction_rejected(self, txid: str, error_type) -> None:
        """Invalidate pending blocks whose required transaction proved invalid."""
        if error_type == errorType.UNKNOWN_OBJ:
            return  # Unknown dependencies may still arrive; use the 5s timeout.
        for blockid, pending in list(self.pending.items()):
            if txid not in pending.missing:
                continue
            self.pending.pop(blockid, None)
            if pending.timer is not None:
                pending.timer.cancel()
            await self.send_error(
                pending.sender,
                errorType.INV_ANC,
                f"Block {blockid} depends on an invalid transaction {txid}.",
            )

    async def _finalize(self, block: dict, sender) -> bool:
        """Execute transactions, validate fees, save atomically, then gossip."""
        blockid = calculate_objectid(block)
        if self.store.has_object(blockid) or blockid in self.processing:
            return True
        self.processing.add(blockid)
        try:
            self._check_base(block)
            transactions = []
            for txid in block["txids"]:
                tx = self.store.get_object(txid)
                if tx is None:
                    raise ObjectValidationError(
                        errorType.UNFINDABLE_OBJ,
                        f"Transaction {txid} is not available.",
                    )
                if not isinstance(tx, dict) or tx.get("type") != "transaction":
                    raise ObjectValidationError(
                        errorType.INV_ANC,
                        f"Object {txid} is not a transaction.",
                    )
                transactions.append(tx)

            height = self.validator.calculate_block_height(block, self.store)
            coinbase = self.validator.validate_block_coinbase(
                transactions, height, self.store,
            )
            coinbase_txid = block["txids"][0] if coinbase is not None else None

            parent_utxo = (
                {} if block["previd"] is None
                else self.store.get_utxo(block["previd"])
            )
            if parent_utxo is None:
                raise ObjectValidationError(
                    errorType.INV_ANC, "Missing UTXO state of the parent block.",
                )

            updated_utxo, total_fees = execute_block(
                parent_utxo, transactions, coinbase_txid, self.store,
            )
            self.validator.validate_coinbase_reward(coinbase, total_fees)
            await self.store.add_validated_block(block, updated_utxo)
        except ObjectValidationError as exc:
            return await self._report(sender, exc.error_type, exc.explanation)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            log.exception("Could not finish block %s", blockid)
            return await self._report(
                sender, errorType.INV_FORM, f"Block processing failed: {exc}",
            )
        finally:
            self.processing.discard(blockid)

        await self.broadcast(blockid)
        return True

    async def close(self) -> None:
        """Cancel timers and background validators during server shutdown."""
        tasks = [p.timer for p in self.pending.values() if p.timer]
        tasks += list(self.background_tasks)
        self.pending.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.background_tasks.clear()
