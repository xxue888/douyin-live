import asyncio
import json
import os
import time
import traceback
from typing import Callable, Optional
from playwright.async_api import async_playwright
from ..config import settings
from ..schemas.models import AppConfig

class DouyinBot:
    def __init__(self, log_callback: Callable[[str, str], None], chat_callback: Callable, status_callback: Callable[[str], None]):
        """
        log_callback: fn(level, message)
        chat_callback: fn(username, message, event_type, metadata)
        status_callback: fn(status_str)
        """
        self.log_callback = log_callback
        self.chat_callback = chat_callback
        self.status_callback = status_callback
        
        self.status = "stopped"  # stopped, logging_in, running
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None
        self.bot_task = None
        
        self.like_count = 0
        self.last_message_time = time.time()
        self._loop_interval = 0.5
        
    def set_status(self, new_status: str):
        self.status = new_status
        self.status_callback(new_status)

    async def start(self, live_url: str, config: AppConfig):
        if self.status != "stopped":
            self.log_callback("WARNING", "机器人已经在运行中")
            return
            
        self.bot_task = asyncio.create_task(self._run_loop(live_url, config))

    async def stop(self):
        self.log_callback("INFO", "正在停止直播间机器人...")
        self.set_status("stopped")
        
        if self.bot_task:
            self.bot_task.cancel()
            try:
                await self.bot_task
            except asyncio.CancelledError:
                pass
            self.bot_task = None

        # Clean up playwright resources
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            self.log_callback("ERROR", f"清理浏览器资源时出错: {e}")
        finally:
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None
            self.log_callback("INFO", "机器人已停止")

    async def _run_loop(self, live_url: str, config: AppConfig):
        try:
            self.log_callback("INFO", "正在启动浏览器引擎...")
            self.set_status("logging_in")
            
            self.playwright = await async_playwright().start()
            
            # Launch Chromium with persistent user profile context (preserves all login sessions & cache)
            profile_dir = settings.DATA_DIR / "browser_profile"
            profile_dir.mkdir(parents=True, exist_ok=True)
            self.log_callback("INFO", "正在加载浏览器环境 (已启用登录会话持久化)...")
            
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            
            # Persistent context opens at least one page automatically
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            
            # Forward browser console logs containing [Bot] to backend
            self.page.on("console", lambda msg: self.log_callback("DEBUG", f"浏览器: {msg.text}") 
                         if "[Bot]" in msg.text else None)
            
            # 1. Navigate to target URL
            self.log_callback("INFO", f"正在打开直播间: {live_url}")
            await self.page.goto(live_url, wait_until="domcontentloaded", timeout=60000)
            
            # 2. Check if logged in
            is_logged_in = await self._check_login_status()
            if not is_logged_in:
                self.log_callback("IMPORTANT", "未检测到登录状态，请在打开的浏览器中完成扫码登录。")
                
                # Wait for user to log in manually (timeout 10 minutes)
                login_timeout = 600
                elapsed = 0
                while elapsed < login_timeout:
                    if self.status == "stopped":
                        return
                    await asyncio.sleep(2)
                    elapsed += 2
                    is_logged_in = await self._check_login_status()
                    if is_logged_in:
                        self.log_callback("INFO", "检测到登录成功！会话已自动持久化保存。")
                        break
                
                if not is_logged_in:
                    self.log_callback("ERROR", "登录超时，机器人停止")
                    await self.stop()
                    return

            self.log_callback("INFO", "登录验证成功，正在初始化直播间监控...")
            self.set_status("running")
            self.last_message_time = time.time()
            
            # Save a snapshot after a delay for developer analysis (to allow dynamic React chat elements to render)
            self.log_callback("INFO", "登录验证成功，正在等待直播间页面完全渲染 (8秒)...")
            await asyncio.sleep(8)
            await self.save_snapshot()
            
            # 3. Inject Chat Monitoring Script
            await self._inject_chat_monitor()
            
            # 4. Main running loop
            while self.status == "running":
                # Periodically query like count and update it
                try:
                    await self._update_like_count()
                except Exception as e:
                    # Ignore minor errors during loop
                    pass
                await asyncio.sleep(self._loop_interval)
                
        except asyncio.CancelledError:
            self.log_callback("INFO", "浏览器控制任务被取消")
        except Exception as e:
            self.log_callback("ERROR", f"浏览器运行发生错误: {str(e)}")
            detail = str(e) or repr(e)
            self.log_callback("ERROR", f"Browser exception detail: {type(e).__name__}: {detail}")
            self.log_callback("DEBUG", traceback.format_exc())
            self.set_status("stopped")
            await self.stop()

    async def _check_login_status(self) -> bool:
        """Determines if the user is logged in by looking for typical UI elements or cookies"""
        if not self.page:
            return False
        try:
            # 1. Primary check: If the chat input box is present on screen, we are definitely logged in and in the room!
            textarea = await self.page.query_selector('textarea[placeholder*="说点什么"], textarea[placeholder*="发言"], textarea[class*="input"], textarea')
            if textarea:
                return True

            # 2. Secondary check: Check for avatar element or similar logged in header features
            avatar = await self.page.query_selector('.avatar, img[class*="avatar"], div[class*="avatar-container"], div[class*="user-avatar"]')
            login_btn = await self.page.query_selector('button:has-text("登录"), div:has-text("登录"), div[class*="login-button"]')
            if avatar and not login_btn:
                return True
                
            # 3. Tertiary check: Check cookies directly
            cookies = await self.context.cookies()
            has_session = any(c['name'] in ['sessionid', 'sid_guard', 'passport_csrf_token', 'sid_tt'] for c in cookies)
            if has_session:
                return True
                
            return False
        except Exception:
            return False

    async def _inject_chat_monitor(self):
        """Exposes Python callbacks and injects JS observer to scrape chat messages"""
        # Expose Python function to page JS context
        await self.context.expose_function("onNewMessage", self._on_new_message_js)
        await self.context.expose_function("onMonitorError", self._on_monitor_error_js)
        
        # Inject JavaScript to monitor DOM additions
        monitor_js = r"""
        (function() {
            console.log("[Bot] Douyin Live Monitor script initialization.");
            
            let activeChatBox = null;
            let observer = null;
            
            // Keep track of processed comment container elements to avoid duplication
            const processedItems = new WeakSet();
            
            function diagnoseDOM() {
                console.log("[Bot] [DIAGNOSTIC] Running DOM diagnosis...");
                
                // 1. Check textareas
                let tas = Array.from(document.querySelectorAll('textarea'));
                console.log("[Bot] [DIAGNOSTIC] Found " + tas.length + " textareas:");
                tas.forEach((ta, i) => {
                    console.log(`[Bot] [DIAGNOSTIC] Textarea ${i}: placeholder="${ta.placeholder}", className="${ta.className}", visible=${ta.offsetWidth > 0}`);
                });
                
                // 2. Check inputs
                let ins = Array.from(document.querySelectorAll('input'));
                console.log("[Bot] [DIAGNOSTIC] Found " + ins.length + " inputs:");
                ins.forEach((input, i) => {
                    console.log(`[Bot] [DIAGNOSTIC] Input ${i}: type="${input.type}", placeholder="${input.placeholder}", className="${input.className}", visible=${input.offsetWidth > 0}`);
                });
                
                // 3. Check editable divs
                let divs = Array.from(document.querySelectorAll('div[contenteditable="true"]'));
                console.log("[Bot] [DIAGNOSTIC] Found " + divs.length + " editable divs.");
                
                // 4. Search scrollable containers on the screen
                let scrollables = Array.from(document.querySelectorAll('div')).filter(el => {
                    let s = window.getComputedStyle(el);
                    return (s.overflowY === 'auto' || s.overflowY === 'scroll') && el.clientHeight > 120;
                });
                console.log("[Bot] [DIAGNOSTIC] Found " + scrollables.length + " scrollable divs.");
                scrollables.forEach((el, i) => {
                    console.log(`[Bot] [DIAGNOSTIC] Scrollable ${i}: className="${el.className}", height=${el.clientHeight}, children=${el.childNodes.length}`);
                });
            }
            
            function findChatContainerByContent() {
                // Find any elements containing a colon
                let candidates = Array.from(document.querySelectorAll('span, div, p')).filter(el => {
                    let text = el.innerText || "";
                    return text.includes("：") && text.length < 120 && text.length > 3;
                });
                
                let scrollContainers = [];
                candidates.forEach(el => {
                    let p = el.parentElement;
                    while (p && p !== document.body) {
                        let style = window.getComputedStyle(p);
                        let isScrollable = style.overflowY === 'auto' || style.overflowY === 'scroll';
                        if (isScrollable && p.clientHeight > 100) {
                            scrollContainers.push(p);
                            break;
                        }
                        p = p.parentElement;
                    }
                });
                
                if (scrollContainers.length > 0) {
                    let counts = new Map();
                    let maxCount = 0;
                    let best = null;
                    scrollContainers.forEach(p => {
                        let count = (counts.get(p) || 0) + 1;
                        counts.set(p, count);
                        if (count > maxCount) {
                            maxCount = count;
                            best = p;
                        }
                    });
                    return best;
                }
                return null;
            }
            
            function findChatContainer() {
                let selectors = [
                    '.webcast-chatroom___list',
                    'div[class*="webcast-chatroom___list"]',
                    'div[class*="chatroom___list"]',
                    'div[class*="chatroom___items"]',
                    'div[class*="webcast-chatroom"]',
                    '[data-testid="chatroom-list"]'
                ];
                for (let sel of selectors) {
                    let el = document.querySelector(sel);
                    if (el) return el;
                }
                
                // Try finding by text content first
                let contentContainer = findChatContainerByContent();
                if (contentContainer) {
                    console.log("[Bot] Found chat box via content-based tracing.");
                    return contentContainer;
                }
                
                // Fallback: search scrollable elements on the right half of the page
                let divs = Array.from(document.querySelectorAll('div, ul, ol, section'));
                let scrollable = divs.filter(el => {
                    let style = window.getComputedStyle(el);
                    let rect = el.getBoundingClientRect();
                    let isScrollable = (style.overflowY === 'auto' || style.overflowY === 'scroll') && el.clientHeight > 150;
                    let isOnRightSide = rect.left > (window.innerWidth / 2);
                    return isScrollable && isOnRightSide;
                });
                
                if (scrollable.length > 0) {
                    let container = scrollable[scrollable.length - 1]; // rightmost/bottommost scroll box
                    console.log("[Bot] Found fallback scrollable chat container. Class: " + container.className);
                    return container;
                }
                return null;
            }
            
            function findChatItem(node) {
                if (!node || node === activeChatBox) return null;
                
                function isItem(el) {
                    if (!el || el === activeChatBox) return false;
                    return (
                        (el.className && typeof el.className === 'string' && 
                         (el.className.includes("item") || el.className.includes("message")) &&
                         !el.className.includes("list")) ||
                        (el.parentElement && typeof el.parentElement.hasAttribute === 'function' && 
                         el.parentElement.hasAttribute('data-index'))
                    );
                }
                
                if (isItem(node)) return node;
                
                let parent = node.parentElement;
                while (parent && parent !== activeChatBox) {
                    if (isItem(parent)) return parent;
                    parent = parent.parentElement;
                }
                
                if (typeof node.querySelector === 'function') {
                    let child = node.querySelector('[class*="item"], [class*="message"]');
                    if (child && isItem(child)) return child;
                }
                
                return null;
            }

            function parseAndEmit(node) {
                // Find the actual chat item by searching both up (ancestors) and down (descendants)
                let itemNode = findChatItem(node);
                
                // If we didn't find a valid item, or it was already processed, skip
                if (!itemNode || processedItems.has(itemNode)) {
                    return;
                }
                
                let text = itemNode.innerText || itemNode.textContent || "";
                if (!text) return;
                
                // Exclude system message notifications (e.g., entered, shared, followed, liked, system warnings)
                if (text.includes("来了") || text.includes("关注了") || text.includes("送了") || 
                    text.includes("分享了") || text.includes("点赞") || text.includes("抖音严禁未成年人") || 
                    text.includes("理性消费") || text.includes("切勿私下交易")) {
                    return;
                }
                
                // Mark this element node as processed to avoid duplicates
                processedItems.add(itemNode);
                
                console.log("[Bot] New comment raw text: " + text.replace(/\n/g, " "));
                
                // Parse standard Chinese colon format "Nickname：Message"
                let idx = text.indexOf("：");
                if (idx === -1) {
                    // Try English colon format
                    idx = text.indexOf(":");
                }
                
                if (idx !== -1) {
                    let name = text.substring(0, idx).trim();
                    let msg = text.substring(idx + 1).trim();
                    
                    // Clean up badges in nickname (like Level/Fans numbers)
                    // e.g. "12 粉丝团 昵称" -> "昵称"
                    name = name.replace(/^[\d\s\w\u4e00-\u9fa5]+粉丝团\s*/, "").trim();
                    name = name.replace(/^[\d\s\w]+/, "").trim(); // Remove leading level numbers
                    
                    if (name && msg) {
                        console.log(`[Bot] Parsed comment - Name: "${name}", Content: "${msg}"`);
                        window.onNewMessage(name, msg);
                        return;
                    }
                }
                
                // Fallback: Check if there are separate span children for nickname and content
                let spans = Array.from(itemNode.querySelectorAll('span'));
                if (spans.length >= 2) {
                    let nameSpan = spans.find(s => s.className.includes("nickname") || s.className.includes("name"));
                    let contentSpan = spans.find(s => s.className.includes("content") || s.className.includes("text"));
                    if (nameSpan && contentSpan) {
                        let name = nameSpan.innerText.trim();
                        let msg = contentSpan.innerText.trim();
                        if (name && msg) {
                            console.log(`[Bot] Parsed fallback spans - Name: "${name}", Content: "${msg}"`);
                            window.onNewMessage(name, msg);
                        }
                    }
                }
            }
            
            function startObserving() {
                let currentChatBox = findChatContainer();
                if (!currentChatBox) {
                    console.log("[Bot] Chat container not found. Running diagnostics and rescheduling check...");
                    diagnoseDOM();
                    setTimeout(startObserving, 5000);
                    return;
                }
                
                // Check if container changed or was recreated
                if (currentChatBox !== activeChatBox || !document.body.contains(activeChatBox)) {
                    if (observer) {
                        console.log("[Bot] Chat container changed or detached. Re-binding observer...");
                        observer.disconnect();
                    }
                    
                    activeChatBox = currentChatBox;
                    console.log("[Bot] Attaching MutationObserver to chat container. Class: " + activeChatBox.className);
                    
                    // Process existing chat elements
                    activeChatBox.childNodes.forEach(node => {
                        if (node.nodeType === Node.ELEMENT_NODE) {
                            parseAndEmit(node);
                        }
                    });
                    
                    observer = new MutationObserver((mutations) => {
                        for (let mutation of mutations) {
                            for (let node of mutation.addedNodes) {
                                if (node.nodeType === Node.ELEMENT_NODE) {
                                    parseAndEmit(node);
                                }
                            }
                        }
                    });
                    
                    observer.observe(activeChatBox, { childList: true, subtree: true });
                }
                
                // Run stability health check every 4 seconds to ensure we keep monitoring even if React re-creates lists
                setTimeout(startObserving, 4000);
            }
            
            // Start the recursive check
            startObserving();
        })();
        """
        monitor_js = r"""
        (() => {
            if (window.__douyinLiveAssistantMonitor) {
                window.__douyinLiveAssistantMonitor.stop();
            }

            console.log("[Bot] Douyin Live Monitor v2 initializing.");

            const processedNodes = new WeakSet();
            const recentFingerprints = new Map();
            const maxFingerprintAgeMs = 90 * 1000;
            const maxNodeTextLength = 220;
            const scanSelectors = [
                '[class*="chat"]',
                '[class*="Chat"]',
                '[class*="comment"]',
                '[class*="Comment"]',
                '[class*="message"]',
                '[class*="Message"]',
                '[class*="webcast"]',
                '[data-index]',
                'li',
                'div'
            ];

            const ignorePieces = [
                "\u6b22\u8fce\u6765\u5230\u6296\u97f3\u76f4\u64ad\u95f4",
                "\u6296\u97f3\u4e25\u7981\u672a\u6210\u5e74\u4eba",
                "\u7406\u6027\u6d88\u8d39",
                "\u5207\u52ff\u79c1\u4e0b\u4ea4\u6613"
            ];

            function normalizeText(text) {
                return (text || "").replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim();
            }

            function compactKey(text) {
                return normalizeText(text).replace(/\s/g, "");
            }

            function isVisible(el) {
                if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
            }

            function cleanupFingerprints() {
                const cutoff = Date.now() - maxFingerprintAgeMs;
                for (const [key, ts] of recentFingerprints.entries()) {
                    if (ts < cutoff) recentFingerprints.delete(key);
                }
            }

            function emitOnce(kind, username, content, metadata = {}) {
                username = normalizeText(username).slice(0, 80);
                content = normalizeText(content).slice(0, 200);
                if (!username || !content) return false;

                cleanupFingerprints();
                const key = `${kind}|${username}|${content}|${metadata.giftName || ""}|${metadata.count || ""}`;
                if (recentFingerprints.has(key)) return false;
                recentFingerprints.set(key, Date.now());

                console.log(`[Bot] ${kind}: ${username} -> ${content}`);
                window.onNewMessage(username, content, kind, metadata);
                return true;
            }

            function cleanUsername(name) {
                return normalizeText(name)
                    .replace(/^[\d\s]+/, "")
                    .replace(/^(LV|Lv|level|Level)\s*\d+\s*/i, "")
                    .replace(/^\u7c89\u4e1d\u56e2\s*/, "")
                    .slice(0, 80);
            }

            function parseGift(text) {
                const normalized = normalizeText(text);
                const key = compactKey(normalized);
                if (!key) return null;

                const giftWords = ["\u9001\u51fa", "\u8d60\u9001", "\u9001\u4e86", "\u9001", "\u793c\u7269"];
                if (!giftWords.some(word => key.includes(word))) return null;

                const patterns = [
                    /^(.+?)(?:\u9001\u51fa|\u8d60\u9001|\u9001\u4e86)(.+?)(?:[xX*]\s*(\d+)|\u00d7\s*(\d+)|(\d+)\u4e2a)?$/,
                    /^(.+?)\u9001(.+?)(?:[xX*]\s*(\d+)|\u00d7\s*(\d+)|(\d+)\u4e2a)?$/
                ];
                for (const pattern of patterns) {
                    const match = normalized.match(pattern);
                    if (!match) continue;
                    const username = cleanUsername(match[1]);
                    const giftName = normalizeText(match[2]).replace(/^[\uff1a:]/, "").trim();
                    const count = match[3] || match[4] || match[5] || "1";
                    if (username && giftName && giftName.length <= 80) {
                        return {
                            username,
                            content: `\u9001\u51fa ${giftName} x${count}`,
                            metadata: { giftName, count }
                        };
                    }
                }
                return null;
            }

            function parseComment(text, el) {
                const normalized = normalizeText(text);
                const key = compactKey(normalized);
                if (!key || key.length < 2 || key.length > maxNodeTextLength) return null;
                if (ignorePieces.some(piece => key.includes(piece))) return null;
                if (parseGift(normalized)) return null;

                const colonMatch = normalized.match(/^(.{1,80}?)[\uff1a:]\s*(.{1,200})$/);
                if (colonMatch) {
                    const username = cleanUsername(colonMatch[1]);
                    const content = normalizeText(colonMatch[2]);
                    if (username && content) return { username, content };
                }

                const namedNodes = Array.from(el.querySelectorAll('[class*="name"], [class*="nick"], [class*="user"]'));
                const contentNodes = Array.from(el.querySelectorAll('[class*="content"], [class*="text"], [class*="message"], [class*="comment"]'));
                for (const nameNode of namedNodes) {
                    const username = cleanUsername(nameNode.innerText || nameNode.textContent || "");
                    if (!username) continue;
                    for (const contentNode of contentNodes) {
                        if (contentNode === nameNode || nameNode.contains(contentNode)) continue;
                        const content = normalizeText(contentNode.innerText || contentNode.textContent || "");
                        if (content && content !== username && content.length <= 200) {
                            return { username, content };
                        }
                    }
                }

                const spans = Array.from(el.querySelectorAll("span"))
                    .map(span => normalizeText(span.innerText || span.textContent || ""))
                    .filter(Boolean);
                if (spans.length >= 2) {
                    const username = cleanUsername(spans[0]);
                    const content = normalizeText(spans.slice(1).join(" "));
                    if (username && content && content !== username && content.length <= 200) {
                        return { username, content };
                    }
                }

                return null;
            }

            function candidateElements(root) {
                if (!root || root.nodeType !== Node.ELEMENT_NODE) return [];
                const items = [];
                if (isVisible(root)) items.push(root);
                if (typeof root.querySelectorAll === "function") {
                    const nested = root.querySelectorAll(scanSelectors.join(","));
                    for (const el of nested) {
                        if (isVisible(el)) items.push(el);
                    }
                }
                return items;
            }

            function processElement(el) {
                if (!el || processedNodes.has(el) || !isVisible(el)) return;
                if (el.children && el.children.length > 12) return;
                const text = normalizeText(el.innerText || el.textContent || "");
                if (!text || text.length > maxNodeTextLength) return;

                const gift = parseGift(text);
                if (gift) {
                    processedNodes.add(el);
                    emitOnce("gift", gift.username, gift.content, gift.metadata);
                    return;
                }

                const comment = parseComment(text, el);
                if (comment) {
                    processedNodes.add(el);
                    emitOnce("chat", comment.username, comment.content);
                }
            }

            function scan(root = document.body) {
                try {
                    for (const el of candidateElements(root)) {
                        processElement(el);
                    }
                } catch (err) {
                    console.log("[Bot] Monitor scan error: " + (err && err.message ? err.message : err));
                    if (window.onMonitorError) window.onMonitorError(String(err && err.message ? err.message : err));
                }
            }

            const observer = new MutationObserver((mutations) => {
                for (const mutation of mutations) {
                    for (const node of mutation.addedNodes) {
                        scan(node);
                    }
                    if (mutation.type === "characterData" && mutation.target && mutation.target.parentElement) {
                        scan(mutation.target.parentElement);
                    }
                }
            });

            observer.observe(document.body, { childList: true, subtree: true, characterData: true });
            const interval = window.setInterval(() => scan(document.body), 2500);

            window.__douyinLiveAssistantMonitor = {
                stop() {
                    observer.disconnect();
                    window.clearInterval(interval);
                }
            };

            scan(document.body);
            console.log("[Bot] Douyin Live Monitor v2 ready.");
        })();
        """
        await self.page.evaluate(monitor_js)
        self.log_callback("INFO", "已成功注入弹幕监听脚本")

    def _on_new_message_js(self, username: str, content: str, event_type: str = "chat", metadata: Optional[dict] = None):
        # Update last interaction time
        self.last_message_time = time.time()
        # Dispatch to callback
        self.chat_callback(username, content, event_type, metadata or {})

    def _on_monitor_error_js(self, reason: str):
        self.log_callback("WARNING", f"网页监听脚本报告异常: {reason}，系统将自动捕获直播间网页快照进行分析。")
        asyncio.create_task(self.save_snapshot())

    async def save_snapshot(self):
        if not self.page:
            return
        try:
            html_content = await self.page.content()
            snapshot_path = settings.DATA_DIR / "page_snapshot.html"
            with open(snapshot_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            self.log_callback("INFO", f"网页快照已保存至: {snapshot_path}")
        except Exception as e:
            self.log_callback("ERROR", f"网页快照保存失败: {e}")

    async def _update_like_count(self):
        """Polls like count from page using regex selectors and updates state"""
        if not self.page:
            return
            
        like_js = r"""
        (function() {
            let elements = Array.from(document.querySelectorAll('span, div, p'));
            for (let el of elements) {
                let text = el.innerText || "";
                let match = text.match(/(?:本场点赞|点赞|赞)\s*[:：]?\s*(\d+(?:\.\d+)?)(万|k|K)?/);
                if (match) {
                    let num = parseFloat(match[1]);
                    let suffix = match[2];
                    let total = num;
                    if (suffix === '万') total = num * 10000;
                    else if (suffix === 'k' || suffix === 'K') total = num * 1000;
                    return Math.floor(total);
                }
            }
            return 0;
        })()
        """
        likes = await self.page.evaluate(like_js)
        if likes and likes > self.like_count:
            self.like_count = likes

    async def send_message(self, content: str) -> bool:
        if not self.page or self.status != "running":
            self.log_callback("WARNING", "发送失败：机器人未处于运行状态")
            return False
            
        try:
            # Locate visible chat input box
            textarea = None
            input_selectors = [
                '#chatInput div[contenteditable="true"]',
                '#chatInput textarea',
                '#chatInput input',
                'div[class*="input-container"] div[contenteditable="true"]',
                'div[class*="chatroom___input"] div[contenteditable="true"]',
                'textarea[placeholder*="说点什么"]:visible',
                'textarea[placeholder*="发言"]:visible',
                'div[contenteditable="true"]:visible',
                'input[placeholder*="说点什么"]:visible',
                '[class*="chatroom___input"]:visible',
                '[class*="chat-input"]:visible'
            ]
            for selector in input_selectors:
                el = await self.page.query_selector(selector)
                if el and await el.is_visible():
                    textarea = el
                    break
            
            if not textarea:
                self.log_callback("ERROR", "未找到聊天输入框，无法发送消息")
                await self.save_snapshot()
                # Run diagnostic to find what elements are visible on page
                inputs_info = await self.page.evaluate("""() => {
                    let inputs = Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"], div'));
                    let matches = inputs.filter(el => {
                        let text = (el.placeholder || el.className || el.innerText || "").toLowerCase();
                        return text.includes("input") || text.includes("textarea") || text.includes("说点") || text.includes("发言") || text.includes("chat");
                    });
                    return matches.slice(0, 5).map(el => `${el.tagName} (class="${el.className}", placeholder="${el.placeholder || ''}", visible=${el.offsetWidth > 0})`).join(' | ');
                }""")
                self.log_callback("DEBUG", f"诊断结果 - 类似输入框的元素: {inputs_info}")
                return False
                
            self.log_callback("DEBUG", f"[Bot] 选中聊天输入框. 正在清空并模拟键盘键入: '{content}'")
            await textarea.click()
            
            # React clears standard value
            await textarea.fill("") 
            
            # Simulate real typing sequentially to trigger page React/Vue state changes
            if hasattr(textarea, "press_sequentially"):
                await textarea.press_sequentially(content, delay=40)
            else:
                await textarea.type(content, delay=40)
                
            # Verify value actually typed
            typed_val = await textarea.evaluate("el => el.value || el.innerText")
            if not typed_val:
                # Force fill if sequential typing was bypassed
                await textarea.fill(content)
                
            # Locate visible send button
            send_btn = None
            btn_selectors = [
                '#chatInput [class*="send-btn"]',
                '#chatInput svg[type="button"]',
                '#chatInput button',
                'button:has-text("发送"):visible',
                'div[class*="send-btn"]:visible',
                '[class*="send-btn"]:visible',
                'span:has-text("发送"):visible'
            ]
            for selector in btn_selectors:
                el = await self.page.query_selector(selector)
                if el and await el.is_visible():
                    send_btn = el
                    break
            
            if send_btn:
                self.log_callback("DEBUG", "[Bot] 找到【发送】按钮，正在执行点击操作...")
                await send_btn.click()
            else:
                self.log_callback("DEBUG", "[Bot] 未找到【发送】按钮，正在回车发送...")
                await textarea.press("Enter")
                
            self.log_callback("INFO", f"已成功向公屏发送消息: {content}")
            return True
        except Exception as e:
            self.log_callback("ERROR", f"向公屏发送消息失败: {str(e)}")
            return False
