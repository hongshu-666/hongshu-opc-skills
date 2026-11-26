"""Four independent media cases; offline fixtures do not certify external model accuracy."""
from pathlib import Path
import json
import sys
import tempfile
import time
import unittest

from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from media_common import acquisition, acquisition_denied, fetch_verified_media, merge_transcript


class MediaCases(unittest.TestCase):
    def test_unauthenticated_403_allows_route_b(self):
        from douyin_collect import _candidate_urls, media_script, prepare_one

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "source.json"
            path.write_text("{}", encoding="utf-8")
            with patch("media_common.subprocess.run") as mocked_curl, patch("media_common.executable", return_value="curl"):
                mocked_curl.return_value.returncode = 22
                mocked_curl.return_value.stderr = "curl: (22) The requested URL returned error: 403"
                with self.assertRaisesRegex(RuntimeError, "403"):
                    fetch_verified_media(["blob:https://www.douyin.com/abc", "https://v26-web.douyinvod.com/test"], "douyin", root / "media.m4a", state_path=path)
            saved_acq = json.loads(path.read_text(encoding="utf-8"))["acquisition"]
            self.assertFalse(saved_acq.get("blocked"))
            self.assertEqual(saved_acq["attempts"], [{"route": "A", "outcome": "failed", "detail": "curl 退出码 22: curl: (22) The requested URL returned error: 403"}])
            state = acquisition(path, "begin", route="B")
            self.assertEqual([a["route"] for a in state["acquisition"]["attempts"]], ["A", "B"])

            dy_info = {
                "url": "https://www.douyin.com/video/7310051440246967590",
                "title": "学会好好说话",
                "author": "胡说老王",
                "published": "2023-12-08",
                "output_dir": str(root / "out"),
                "videos": [
                    {"src": "blob:https://www.douyin.com/4d955d61", "duration": 370.134, "sources": ["https://v26-web.douyinvod.com/video/tos/x", "https://www.douyin.com/aweme/v1/play/?video_id=v02"]},
                    {"src": "", "duration": None},
                ],
                "audioUrls": ["https://v26-web.douyinvod.com/x/media-audio-und-mp4a/?a=6383"],
            }
            cands = _candidate_urls(dy_info)
            self.assertIn("/aweme/v1/play/", cands[0])
            self.assertIn("media-audio-und-mp4a", cands[-1])
            obs_file = root / "obs.json"
            obs_file.write_text(json.dumps(dy_info, ensure_ascii=False), encoding="utf-8")
            ms = media_script(obs_file, root / "media.js")
            self.assertEqual(ms["candidate_count"], 3)

            dy_src = root / "dy-source.json"
            dy_src.write_text(json.dumps(dy_info, ensure_ascii=False), encoding="utf-8")
            with patch("media_common.subprocess.run") as mocked_curl, patch("media_common.executable", return_value="curl"):
                mocked_curl.return_value.returncode = 22
                mocked_curl.return_value.stderr = "HTTP Error 403: Forbidden"
                needs = prepare_one(dy_src)
            self.assertEqual(needs["status"], "needs_media")
            self.assertEqual(needs["route"], "B")
            self.assertTrue(Path(needs["media_script"]).is_file())

    def test_finalize_blocks_unpunctuated_wall_of_text(self):
        from douyin_collect import finalize

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            reviewed = root / "reviewed.txt"
            clauses = [
                f"第{i}步先梳理团队当前卡住的核心流程并明确责任边界与交接节点，"
                for i in range(1, 16)
            ]
            reviewed.write_text("".join(clauses), encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "id": "7455642467472395558",
                        "url": "https://www.douyin.com/video/7455642467472395558",
                        "title": "如何搞定不配合的同事？",
                        "published": "2025-01-03",
                        "author": "夏鹏",
                        "like_count": "26.1万",
                        "content_type": "视频",
                        "tags": ["职场沟通"],
                        "started_at_epoch": time.time(),
                        "timings": {"prepare_total": 0},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "无句末标点"):
                finalize(manifest, reviewed, root / "notes")

    def test_finalize_blocks_severe_truncation_summary(self):
        from douyin_collect import finalize

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft = root / "draft.txt"
            sentences = [
                f"第{i}点原因在于执行过程中缺乏清晰的阶段里程碑与复盘机制，导致成员对结果预期不一致。"
                for i in range(1, 10)
            ]
            draft.write_text("".join(sentences), encoding="utf-8")
            reviewed = root / "reviewed.txt"
            reviewed.write_text("团队执行力上不去主要是目标不清。", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "id": "7455642467472395559",
                        "url": "https://www.douyin.com/video/7455642467472395559",
                        "title": "为什么团队执行力上不去",
                        "published": "2025-01-04",
                        "author": "夏鹏",
                        "like_count": "1.2万",
                        "content_type": "视频",
                        "tags": ["团队管理"],
                        "draft": str(draft),
                        "started_at_epoch": time.time(),
                        "timings": {"prepare_total": 0},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "疑似实质删段"):
                finalize(manifest, reviewed, root / "notes")

    def test_three_speakers_word_alignment(self):
        asr = {
            "text": "甲乙丙",
            "segments": [
                {
                    "start": 0,
                    "end": 3,
                    "text": "甲乙丙",
                    "words": [{"start": i, "end": i + 1, "word": word} for i, word in enumerate("甲乙丙")],
                }
            ],
        }
        rows = [{"start": i, "end": i + 1, "speaker": str(i)} for i in range(3)]
        body, count = merge_transcript(asr, rows, 3)
        self.assertEqual(count, 3)
        for number, word in enumerate("甲乙丙", 1):
            self.assertIn(f"说话人{number}：{word}", body)


if __name__ == "__main__":
    unittest.main()
