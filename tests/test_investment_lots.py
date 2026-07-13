from __future__ import annotations

from datetime import date
import unittest

from holding_core.investment_lots import AcquisitionLot, FifoLotError, allocate_fifo_share_sale


class InvestmentLotsTest(unittest.TestCase):
    def test_allocates_oldest_lots_first_with_cent_exact_residual(self) -> None:
        allocation = allocate_fifo_share_sale(
            lots=(
                AcquisitionLot(
                    id="lot-new",
                    acquisition_date=date(2025, 2, 1),
                    original_share_count=100,
                    remaining_share_count=100,
                    original_cost_basis=30000,
                    remaining_cost_basis=30000,
                ),
                AcquisitionLot(
                    id="lot-old",
                    acquisition_date=date(2025, 1, 1),
                    original_share_count=100,
                    remaining_share_count=100,
                    original_cost_basis=10000,
                    remaining_cost_basis=10000,
                ),
            ),
            sale_date=date(2025, 3, 1),
            sold_share_count=150,
        )

        self.assertEqual(allocation.cost_basis_reduction, 25000)
        self.assertEqual(allocation.remaining_share_count, 50)
        self.assertEqual(allocation.remaining_cost_basis, 15000)
        self.assertEqual(
            [item.model_dump() for item in allocation.allocations],
            [
                {
                    "lot_id": "lot-old",
                    "acquisition_date": date(2025, 1, 1),
                    "share_count": 100,
                    "cost_basis": 10000.0,
                },
                {
                    "lot_id": "lot-new",
                    "acquisition_date": date(2025, 2, 1),
                    "share_count": 50,
                    "cost_basis": 15000.0,
                },
            ],
        )

    def test_rounds_partial_lot_and_leaves_exact_remainder(self) -> None:
        allocation = allocate_fifo_share_sale(
            lots=(
                AcquisitionLot(
                    id="lot",
                    acquisition_date=date(2025, 1, 1),
                    original_share_count=3,
                    remaining_share_count=3,
                    original_cost_basis=100,
                    remaining_cost_basis=100,
                ),
            ),
            sale_date=date(2025, 2, 1),
            sold_share_count=1,
        )

        self.assertEqual(allocation.cost_basis_reduction, 33.33)
        self.assertEqual(allocation.remaining_cost_basis, 66.67)

    def test_rejects_missing_lots_oversale_and_future_lots(self) -> None:
        with self.assertRaisesRegex(FifoLotError, "missing_acquisition_lots"):
            allocate_fifo_share_sale(lots=(), sale_date=date(2025, 2, 1), sold_share_count=1)
        lot = AcquisitionLot(
            id="lot",
            acquisition_date=date(2025, 2, 1),
            original_share_count=1,
            remaining_share_count=1,
            original_cost_basis=100,
            remaining_cost_basis=100,
        )
        with self.assertRaisesRegex(FifoLotError, "sale_exceeds_lots"):
            allocate_fifo_share_sale(lots=(lot,), sale_date=date(2025, 3, 1), sold_share_count=2)
        with self.assertRaisesRegex(FifoLotError, "future_acquisition_lot"):
            allocate_fifo_share_sale(lots=(lot,), sale_date=date(2025, 1, 1), sold_share_count=1)


if __name__ == "__main__":
    unittest.main()
