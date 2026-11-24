"""M23: reference links are clickable, stable, and honestly labelled.

The rule that shapes this module: a link the daemon did not read must not look like a source it used.
So every link is a *search* URL (stable for any spelling), the block says "searches, not pages I read",
and only space topics get NASA and Space.com.

Covered here: topic extraction from a question, space versus general topics, URL encoding, dedupe, the
labels, and the three places links appear - a local answer, a model answer, and the HTTP endpoint.
"""
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chat_app  # noqa: E402
import links  # noqa: E402
import micronaut_server  # noqa: E402
import session_log  # noqa: E402
import user_memory  # noqa: E402


class M23ReferenceLinks(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        session_log.SESSIONS_DIR = Path(tempfile.mkdtemp())
        user_memory.EVENTS = Path(self.folder.name) / "user.events.jsonl"

    def tearDown(self):
        self.folder.cleanup()

    # -- topic extraction ----------------------------------------------------------------------
    def test_the_topic_is_the_subject_not_the_question(self):
        self.assertEqual(links.topic("what is saturn"), "saturn")
        self.assertEqual(links.topic("Who is Shakespeare?"), "Shakespeare")
        self.assertEqual(links.topic("tell me about the moon landing"), "moon landing")
        self.assertEqual(links.topic("explain quantum chromodynamics"), "quantum chromodynamics")
        self.assertEqual(links.topic("hello"), "", "a greeting is not a subject")

    def test_a_question_without_a_subject_gets_no_links(self):
        self.assertEqual(links.for_text("how are you"), [])
        self.assertEqual(links.references(""), [])

    # -- the link set --------------------------------------------------------------------------
    def test_general_topics_get_two_authoritative_searches(self):
        sites = [link["site"] for link in links.references("shakespeare")]
        self.assertEqual(sites, ["wikipedia", "britannica"])

    def test_space_topics_also_get_nasa_and_space_com(self):
        for query in ("saturn", "the moon landing", "mars", "hubble telescope"):
            sites = [link["site"] for link in links.references(query)]
            self.assertIn("nasa", sites, query)
            self.assertIn("space.com", sites, query)

    def test_links_are_https_and_url_encoded(self):
        for link in links.references("what is C++ & rust"):
            self.assertTrue(link["url"].startswith("https://"), link)
            self.assertNotIn(" ", link["url"], link)
        encoded = links.references("C++ & rust")[0]["url"]
        self.assertIn("%2B%2B", encoded)
        self.assertIn("%26", encoded)

    def test_links_are_deduplicated_and_bounded(self):
        found = links.references("saturn", limit=10)
        self.assertEqual(len({link["url"] for link in found}), len(found))
        self.assertLessEqual(len(found), 4)

    def test_the_block_says_what_the_links_are_not(self):
        block = links.block("what is saturn")
        self.assertIn("searches, not pages I read", block)
        self.assertIn("](", block, "links must be clickable markdown")
        for label in ("Wikipedia", "NASA"):
            self.assertIn(label, block)

    # -- where links appear --------------------------------------------------------------------
    def test_a_local_answer_carries_links(self):
        async def ask():
            app = chat_app.ChatApp()
            app.stream_llm_response = lambda text: None
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                return app.local_answer("what is saturn"), app

        local, app = asyncio.run(ask())
        self.assertIsNotNone(local)
        body = local[1]
        self.assertIn("Sixth planet", body)
        self.assertIn("nasa.gov", body)
        self.assertIn("delve deeper", body.lower())

    def test_a_model_answer_gets_links_only_when_it_has_none(self):
        async def drive(answer):
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                class Resp:
                    def __init__(self):
                        self.text = ""
                    def update(self, value):
                        self.text += value
                response = Resp()
                returned = app.maybe_reference(answer, last_user="what is saturn", response=response)
                return returned, response.text

        plain, mounted = asyncio.run(drive("Saturn is a gas giant with rings."))
        self.assertIn("wikipedia.org", plain)
        self.assertIn("wikipedia.org", mounted)

        already = asyncio.run(drive("See [Saturn](https://example.org/saturn) for detail."))
        self.assertEqual(already[0], "See [Saturn](https://example.org/saturn) for detail.")

    def test_a_non_question_answer_gets_no_links(self):
        async def drive():
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                class Resp:
                    text = ""
                    def update(self, value):
                        self.text += value
                response = Resp()
                return app.maybe_reference("Anything.", last_user="hello", response=response)

        self.assertEqual(asyncio.run(drive()), "Anything.")

    def test_the_endpoint_returns_links_for_a_topic(self):
        server = micronaut_server.serve(0, block=False)
        try:
            engine = micronaut_server.Engine()
            payload = engine.chat("what is saturn")
            self.assertEqual(payload["kind"], "aiml")
            sites = [link["site"] for link in payload["links"]]
            self.assertIn("wikipedia", sites)
            self.assertIn("nasa", sites)
        finally:
            server.server_close()

    def test_the_links_command_has_a_route(self):
        async def drive():
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                app.handle_command("/links saturn")
                await pilot.pause()
                view = app.query_one("#chat-view")
                return [getattr(child, "source", "") for child in view.children][-1]

        rendered = asyncio.run(drive())
        self.assertIn("Reference links for saturn", rendered)
        self.assertIn("wikipedia.org", rendered)


if __name__ == "__main__":
    unittest.main()
