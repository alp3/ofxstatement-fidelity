import os
import glob
import pytest
from ofxstatement.ofx import OfxWriter
from ofxstatement.ui import UI
import xml.dom.minidom
from decimal import Decimal

from ofxstatement_fidelity.plugin import FidelityPlugin

# Dynamically find all CSV files in the tests directory
HERE = os.path.dirname(__file__)
CSV_FILES = glob.glob(os.path.join(HERE, "*.csv"))


@pytest.mark.parametrize("filename", CSV_FILES)
def test_fidelity_csv_parsing(filename):
    """
    Run the parser against every CSV file found in the tests/ directory.
    """
    # SKIP empty files (like the ghost file if you didn't delete it)
    # to prevent the "min() arg is empty" crash
    if os.path.getsize(filename) == 0:
        pytest.skip(f"Skipping empty file: {filename}")

    plugin = FidelityPlugin(UI(), {})
    parser = plugin.get_parser(filename)

    statement = parser.parse()

    # Basic Validations
    assert statement is not None
    assert statement.broker_id == "Fidelity"
    assert statement.currency == "USD"

    # Ensure we actually parsed some lines (assuming test files aren't empty)
    assert len(statement.invest_lines) > 0, f"No transactions found in {filename}"

    # Verify every line has the critical fields required by OFX
    for line in statement.invest_lines:
        line.assert_valid()
        assert line.id is not None
        assert line.date is not None
        assert line.amount is not None


def test_fidelity_t_bill_purchase_and_sale() -> None:
    plugin = FidelityPlugin(UI(), {})
    here = os.path.dirname(__file__)
    fidelity_filename = os.path.join(here, "tbill.csv")

    parser = plugin.get_parser(fidelity_filename)
    statement = parser.parse()

    assert statement is not None
    assert len(statement.invest_lines) == 2

    purchase = statement.invest_lines[0]
    assert purchase.trntype == "BUYDEBT"
    assert purchase.trntype_detailed is None
    assert purchase.security_id == "912797SB4"
    assert purchase.units == Decimal("14000")
    assert purchase.amount is not None
    assert purchase.amount == Decimal("-13870.83")
    assert purchase.fees is None
    assert purchase.units is not None
    assert purchase.unit_price == (abs(purchase.amount) / purchase.units) * Decimal(
        "100"
    )
    assert purchase.date is not None
    assert (
        purchase.date.year == 2025
        and purchase.date.month == 12
        and purchase.date.day == 7
    )

    redemption = statement.invest_lines[1]
    assert redemption.trntype == "SELLDEBT"
    assert redemption.trntype_detailed is None
    assert redemption.security_id == "912797SB4"
    assert redemption.units == Decimal("14000")
    assert redemption.amount == Decimal("14000")
    assert redemption.unit_price == Decimal("100")
    assert redemption.fees is None
    assert redemption.date is not None
    assert (
        redemption.date.year == 2025
        and redemption.date.month == 12
        and redemption.date.day == 8
    )
    assert statement.start_date is not None
    assert statement.end_date is not None
    assert statement.start_date.strftime("%Y-%m-%d") == "2025-12-07"
    assert statement.end_date.strftime("%Y-%m-%d") == "2025-12-08"


def test_fidelity_t_bill_cusip_and_debtinfo_in_ofx() -> None:
    plugin = FidelityPlugin(UI(), {})
    here = os.path.dirname(__file__)
    fidelity_filename = os.path.join(here, "tbill.csv")
    parser = plugin.get_parser(fidelity_filename)
    statement = parser.parse()
    assert statement is not None

    # Ensure OFX generation marks the CUSIP as a DEBTINFO/CUSIP in both the security list and transactions
    writer = OfxWriter(statement)
    assert statement.end_date is not None
    writer.genTime = statement.end_date  # deterministic timestamp
    _, _, payload = writer.toxml().partition("\r\n\r\n")
    dom = xml.dom.minidom.parseString(payload)

    def text(node, tag_name: str) -> str:
        elems = node.getElementsByTagName(tag_name)
        return elems[0].firstChild.nodeValue if elems and elems[0].firstChild else ""

    debt_infos = dom.getElementsByTagName("DEBTINFO")
    assert len(debt_infos) == 1
    assert text(debt_infos[0], "UNIQUEID") == "912797SB4"
    assert text(debt_infos[0], "UNIQUEIDTYPE") == "CUSIP"
    assert not debt_infos[0].getElementsByTagName("TICKER")

    stock_infos = dom.getElementsByTagName("STOCKINFO")
    assert len(stock_infos) == 0

    secid_nodes = dom.getElementsByTagName("SECID")
    secids = {
        text(node, "UNIQUEID"): text(node, "UNIQUEIDTYPE") for node in secid_nodes
    }
    # One SECID in the seclist plus two in the transaction list; all should report CUSIP
    assert secids["912797SB4"] == "CUSIP"

    invtranlist = dom.getElementsByTagName("INVTRANLIST")
    assert len(invtranlist) == 1

    txn_secids = invtranlist[0].getElementsByTagName("SECID")
    assert len(txn_secids) == 2  # BUYDEBT + SELLDEBT

    for secid in txn_secids:
        assert text(secid, "UNIQUEID") == "912797SB4"
        assert text(secid, "UNIQUEIDTYPE") == "CUSIP"
