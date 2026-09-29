"""Validate the benchmark's fairness, accounting, and reproducibility."""

import copy
import unittest

from sample_data import get_agents, get_posts, get_scenarios, stable_random
from simulate import CONFIG, community_counts, compare, evaluate, run_policy, score, validate_rule


class BenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agents = get_agents()
        cls.posts = get_posts()
        cls.scenarios = get_scenarios()
        cls.initial = cls.scenarios[0]["initial_endorsements"]
        cls.baseline = run_policy(cls.agents, cls.posts, cls.initial, 11, "baseline")
        cls.capped = run_policy(cls.agents, cls.posts, cls.initial, 11, "capped")

    def test_cap_counts_unique_supporters(self):
        agents_by_id = {a["id"]: a for a in self.agents}
        self.assertEqual(community_counts(["a01", "a01", "a02", "a03"], agents_by_id), [3, 0, 0, 0, 0])
        self.assertEqual(score([10, 0, 0, 0, 0], "baseline"), 10)
        self.assertEqual(score([10, 0, 0, 0, 0], "capped"), 2)
        self.assertEqual(score([2, 2, 2, 2, 2], "capped"), 10)

    def test_fixtures_are_valid_and_support_totals_are_matched(self):
        self.assertEqual(len(self.agents), 50)
        self.assertEqual(len(self.posts), 40)
        agents_by_id = {a["id"]: a for a in self.agents}
        for scenario in self.scenarios:
            for post in self.posts:
                ids = scenario["initial_endorsements"][post["id"]]
                self.assertEqual(len(ids), len(set(ids)))
                self.assertNotIn(post["author_id"], ids)
                self.assertTrue(all(agent_id in agents_by_id for agent_id in ids))
                self.assertEqual(len(ids), len(self.initial[post["id"]]))
        for post_id in ("p05", "p14", "p23", "p32"):
            concentrated = community_counts(self.scenarios[0]["initial_endorsements"][post_id], agents_by_id)
            distributed = community_counts(self.scenarios[2]["initial_endorsements"][post_id], agents_by_id)
            self.assertEqual(max(concentrated), 9)
            self.assertLessEqual(max(distributed), 2)
        for community in range(5):
            self.assertEqual(len({a["political_view"] for a in self.agents if a["community"] == community}), 5)

    def test_trace_has_no_duplicate_or_self_exposure_and_one_action_per_round(self):
        posts_by_id = {p["id"]: p for p in self.posts}
        for result in (self.baseline, self.capped):
            seen = {a["id"]: set() for a in self.agents}
            final_actions = 0
            for snapshot in result["rounds"]:
                for agent_id, feed in snapshot["feeds"].items():
                    self.assertEqual(len(feed), CONFIG["feed_size"])
                    self.assertLessEqual(sum(i["action"] != "none" for i in feed), 1)
                    for item in feed:
                        self.assertNotIn(item["post_id"], seen[agent_id])
                        self.assertNotEqual(posts_by_id[item["post_id"]]["author_id"], agent_id)
                        seen[agent_id].add(item["post_id"])
                        if item["action"] != "none":
                            final_actions += 1
                            self.assertIn(agent_id, result["final_endorsements"][item["post_id"]])
            self.assertEqual(result["metrics"]["total_impressions"], 900)
            self.assertEqual(result["metrics"]["total_actions"], final_actions)
            added_support = sum(len(ids) - len(self.initial[post_id])
                                for post_id, ids in result["final_endorsements"].items())
            self.assertEqual(added_support, final_actions)

    def test_metrics_match_delivered_trace(self):
        labels = {p["id"]: p["label"] for p in self.posts}
        for result in (self.baseline, self.capped):
            harmful, reach = 0, set()
            for snapshot in result["rounds"]:
                for agent, feed in snapshot["feeds"].items():
                    for item in feed:
                        if labels[item["post_id"]] == "antisemitic":
                            harmful += 1
                            reach.add(agent)
            self.assertEqual(result["metrics"]["harmful_impressions"], harmful)
            self.assertEqual(result["metrics"]["harmful_reach_count"], len(reach))
            self.assertAlmostEqual(result["metrics"]["harmful_exposure_rate"], harmful / 900)
            m = result["metrics"]
            self.assertEqual(m["total_impressions"], m["harmful_impressions"] + m["ordinary_impressions"]
                             + m["counterspeech_impressions"] + m["ambiguous_impressions"])

    def test_ambiguous_denominator_and_zero_retention(self):
        posts = {"h": {"label": "antisemitic"}, "u": {"label": "ambiguous"},
                 "c": {"label": "counterspeech"}, "o": {"label": "ordinary"}}
        rounds = [{"feeds": {"a": [{"post_id": "h", "action": "none"}, {"post_id": "u", "action": "none"}],
                              "b": [{"post_id": "c", "action": "like"}, {"post_id": "o", "action": "none"}]}}]
        metrics = evaluate(rounds, posts, 2)
        self.assertEqual(metrics["harmful_exposure_rate"], 0.25)
        self.assertEqual(metrics["harmful_reach_rate"], 0.5)
        self.assertEqual(metrics["counterspeech_actions"], 1)
        self.assertIsNone(compare(metrics, metrics)["ordinary_engagement_retention"])
        self.assertEqual(compare(metrics, metrics)["harmful_exposure_delta_pp"], 0)

    def test_labels_text_and_jewish_life_tag_cannot_change_behavior(self):
        relabeled = copy.deepcopy(self.posts)
        for post in relabeled:
            post["label"] = "ordinary"
            post["text"] = "Changed evaluation text"
            post["about_jewish_life"] = False
        result = run_policy(self.agents, relabeled, self.initial, 11, "baseline")
        self.assertEqual([r["feeds"] for r in result["rounds"]], [r["feeds"] for r in self.baseline["rounds"]])
        self.assertEqual(result["final_endorsements"], self.baseline["final_endorsements"])
        self.assertEqual(result["metrics"]["harmful_impressions"], 0)

    def test_repeated_run_matches_without_mutating_inputs(self):
        before = copy.deepcopy((self.agents, self.posts, self.initial))
        self.assertEqual(run_policy(self.agents, self.posts, self.initial, 11, "baseline"), self.baseline)
        self.assertEqual((self.agents, self.posts, self.initial), before)
        expected = stable_random(11, 1, "a01", "p01", "action")
        stable_random(71, 6, "a50", "p40", "action")
        self.assertEqual(stable_random(11, 1, "a01", "p01", "action"), expected)

    def test_lab_rejects_unknown_rule_or_invalid_cap(self):
        for rule, cap in (("unknown", 2), ("baseline", 2), ("capped", 0), ("capped", 11)):
            with self.assertRaises(ValueError):
                validate_rule(rule, cap)


if __name__ == "__main__":
    unittest.main()
