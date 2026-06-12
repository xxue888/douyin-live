import unittest
from unittest.mock import patch, MagicMock
import os
import json
import tempfile
from pathlib import Path

# Adjust path to import app modules correctly
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.schemas.models import AppConfig, KeywordRule, ScheduledMessage
from app.database import load_config, save_config
from app.core.reply_engine import evaluate_comment, _recent_replies

class TestAssistantBackend(unittest.TestCase):
    def setUp(self):
        # Clear recent replies history
        _recent_replies.clear()
        
        # Define a mock configuration
        self.config = AppConfig(
            live_url="https://live.douyin.com/test",
            ai_reply_enabled=True,
            llm_provider="openai",
            openai_api_key="test-key",
            system_prompt="Test Prompt",
            rules=[
                KeywordRule(keyword="多少钱", reply="99元包邮"),
                KeywordRule(keyword="怎么买", reply="点击小黄车")
            ],
            scheduled_messages=[
                ScheduledMessage(interval=300, content="欢迎光临", enabled=True)
            ]
        )

    def test_rule_matching_priority(self):
        """Test that exact and substring keyword rules are matched first"""
        # Test exact match
        result = evaluate_comment("张三", "多少钱", self.config)
        self.assertIsNotNone(result)
        reply, source = result
        self.assertEqual(reply, "99元包邮")
        self.assertEqual(source, "rule")

        # Test substring match
        result = evaluate_comment("李四", "请问这个东西多少钱啊？", self.config)
        self.assertIsNotNone(result)
        reply, source = result
        self.assertEqual(reply, "99元包邮")
        self.assertEqual(source, "rule")

    @patch("app.core.reply_engine.generate_reply")
    def test_ai_reply_fallback(self, mock_generate):
        """Test that AI is called when no rules match and AI replies are enabled"""
        mock_generate.return_value = "谢谢支持～"
        
        result = evaluate_comment("王五", "主播今天真漂亮", self.config)
        self.assertIsNotNone(result)
        reply, source = result
        self.assertEqual(reply, "谢谢支持～")
        self.assertEqual(source, "ai")
        mock_generate.assert_called_once()

    @patch("app.core.reply_engine.generate_reply")
    def test_ai_reply_disabled(self, mock_generate):
        """Test that no reply is generated if rules don't match and AI is disabled"""
        self.config.ai_reply_enabled = False
        
        result = evaluate_comment("赵六", "主播好帅", self.config)
        self.assertIsNone(result)
        mock_generate.assert_not_called()

    @patch("app.core.reply_engine.generate_reply")
    def test_duplicate_prevention(self, mock_generate):
        """Test that the engine alters the response slightly to avoid sending identical texts"""
        # First call gets a response
        mock_generate.return_value = "你好呀"
        reply1, source1 = evaluate_comment("客A", "在吗", self.config)
        
        # Second call gets same response from mock, should be altered
        reply2, source2 = evaluate_comment("客B", "在吗", self.config)
        
        self.assertNotEqual(reply1, reply2)
        self.assertTrue(reply2.startswith("你好呀"))

if __name__ == "__main__":
    unittest.main()
