"""M97: a URI-addressed store - schemas as contracts, rows as instances, and the two gaps measured.

The store is real here: it writes. Everything it refuses is refused before a write, and the two database problems the
review names - queries without an index, and referential integrity - are visible in the API rather than assumed away.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uri_store as U  # noqa: E402

INVOICES = {
    "$schema": "https://json-schema.org",
    "$id": "urn:db:finance:table:invoices:v1",
    "type": "object",
    "required": ["invoice_id", "customer_uri", "amount"],
    "properties": {"invoice_id": {"type": "string"}, "customer_uri": {"type": "string"},
                   "amount": {"type": "number", "minimum": 0}},
}
CUSTOMERS = {
    "$schema": "https://json-schema.org",
    "$id": "urn:db:crm:table:customers:v1",
    "type": "object", "required": ["name"], "properties": {"name": {"type": "string"}},
}
CUSTOMER = "urn:db:crm:row:customers:cust_441"
INVOICE = "urn:db:finance:row:invoices:inv_90812"


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = U.default_store(Path(self.folder.name))
        self.store.register_schema("urn:db:finance:table:invoices:v1", INVOICES)
        self.store.register_schema("urn:db:crm:table:customers:v1", CUSTOMERS)

    def tearDown(self):
        self.folder.cleanup()

    def seed(self):
        self.store.put(CUSTOMER, {"$schema": "urn:db:crm:table:customers:v1", "name": "Bill"})
        self.store.put(INVOICE, {"$schema": "urn:db:finance:table:invoices:v1",
                                 "invoice_id": "inv_90812", "customer_uri": CUSTOMER,
                                 "amount": 1450.0})

    def test_a_row_round_trips_and_reports_that_it_wrote(self):
        self.seed()
        result = self.store.get(INVOICE)
        self.assertTrue(result["ok"])
        self.assertEqual(result["record"]["amount"], 1450.0)
        self.assertTrue(result["mutation"] is False, "a read is not a mutation")
        written = self.store.put(INVOICE + "", {"$schema": "urn:db:finance:table:invoices:v1",
                                                "invoice_id": "inv_90812", "customer_uri": CUSTOMER,
                                                "amount": 1451.0})
        self.assertTrue(written["mutation"], "a write says so")

    def test_a_write_from_an_unregistered_table_is_refused(self):
        result = self.store.put("urn:db:finance:row:invoices:inv_1",
                                {"$schema": "urn:db:finance:table:unknown:v1", "amount": 1})
        self.assertEqual(result["refused"], "row_invalid")
        self.assertEqual(result["problems"][0]["code"], "schema_not_registered")
        self.assertFalse(result["mutation"])

    def test_a_row_that_breaks_its_schema_is_refused_before_writing(self):
        bad = self.store.put("urn:db:finance:row:invoices:inv_2",
                             {"$schema": "urn:db:finance:table:invoices:v1",
                              "invoice_id": "inv_2", "customer_uri": CUSTOMER, "amount": -5})
        self.assertEqual(bad["refused"], "row_invalid")
        self.assertIn("minimum", [problem["code"] for problem in bad["problems"]])
        self.assertFalse(self.store.get("urn:db:finance:row:invoices:inv_2")["ok"])
        missing = self.store.put("urn:db:finance:row:invoices:inv_3",
                                 {"$schema": "urn:db:finance:table:invoices:v1", "amount": 1})
        self.assertIn("required", [problem["code"] for problem in missing["problems"]])

    def test_a_field_address_resolves_in_either_pointer_style(self):
        self.seed()
        schema_style = self.store.get(INVOICE + "#/properties/amount")
        row_style = self.store.get(INVOICE + "#/amount")
        self.assertEqual(schema_style["record"], 1450.0)
        self.assertEqual(row_style["record"], 1450.0)
        self.assertEqual(schema_style["pointer_style"], "schema")
        self.assertEqual(row_style["pointer_style"], "row")
        self.assertEqual(self.store.get(INVOICE + "#/nope")["refused"], "pointer_not_found")

    def test_a_reference_is_dereferenced_as_a_join(self):
        self.seed()
        joined = self.store.join(INVOICE, "customer_uri")
        self.assertTrue(joined["ok"], joined.get("refused"))
        self.assertEqual(joined["record"]["name"], "Bill")
        self.assertEqual([hop["uri"] for hop in joined["hops"]], [INVOICE, CUSTOMER])

    def test_a_join_to_a_missing_row_reports_the_missing_target(self):
        self.seed()
        self.store.put("urn:db:finance:row:invoices:inv_2",
                       {"$schema": "urn:db:finance:table:invoices:v1", "invoice_id": "inv_2",
                        "customer_uri": "urn:db:crm:row:customers:nobody", "amount": 1})
        joined = self.store.join("urn:db:finance:row:invoices:inv_2", "customer_uri")
        self.assertEqual(joined["refused"], "not_found")
        self.assertEqual(joined["hops"][-1]["uri"], "urn:db:crm:row:customers:nobody")

    def test_a_scan_is_linear_and_says_so(self):
        self.seed()
        self.store.put("urn:db:finance:row:invoices:inv_2",
                       {"$schema": "urn:db:finance:table:invoices:v1", "invoice_id": "inv_2",
                        "customer_uri": CUSTOMER, "amount": 40.0})
        scanned = self.store.scan("urn:db:finance:row:", lambda row: row.get("amount", 0) > 1000)
        self.assertEqual(scanned["scanned"], 2)
        self.assertEqual(scanned["matched"], 1)
        self.assertIn("no index", scanned["note"])

    def test_a_referenced_row_cannot_be_deleted_silently(self):
        self.seed()
        blocked = self.store.delete(CUSTOMER)
        self.assertEqual(blocked["refused"], "referenced")
        self.assertEqual(len(blocked["links"]), 1)
        self.assertFalse(blocked["mutation"])
        self.assertTrue(self.store.get(CUSTOMER)["ok"], "nothing was removed")

    def test_a_forced_delete_records_the_links_it_broke(self):
        self.seed()
        forced = self.store.delete(CUSTOMER, force=True)
        self.assertTrue(forced["mutation"])
        self.assertEqual([link["field"] for link in forced["broken_links"]], ["customer_uri"])
        self.assertEqual(self.store.join(INVOICE, "customer_uri")["refused"], "not_found")

    def test_an_unrouted_prefix_is_refused(self):
        with self.assertRaises(U.StoreError):
            self.store.get("urn:db:other:row:things:x")
        with self.assertRaises(U.StoreError):
            self.store.put("not-a-urn", {})

    def test_the_table_comes_from_the_row_uri(self):
        self.assertEqual(U.table_of(INVOICE), "urn:db:finance:table:invoices:v1")
        with self.assertRaises(U.StoreError):
            U.table_of("urn:db:finance:customers:x")

    def test_the_store_is_not_reachable_from_the_read_only_surface(self):
        import mcp_host

        listing = mcp_host.list_handlers()
        self.assertNotIn("uri_store", json.dumps(listing),
                         "a store that writes is not a read-only MCP tool")
        for row in listing["handlers"]:
            self.assertEqual(row["effect"], "read_only")


if __name__ == "__main__":
    unittest.main()
