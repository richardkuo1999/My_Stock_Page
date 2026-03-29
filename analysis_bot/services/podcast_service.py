import logging
import json
import feedparser
import aiohttp
import aiofiles
import aiofiles.os
import os
import asyncio
import ssl
import certifi
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from sqlmodel import Session, select
from ..database import engine
from ..models.content import Podcast
from ..config import get_settings
from .ai_service import AIService, RequestType

settings = get_settings()
logger = logging.getLogger(__name__)

class PodcastService:
    def __init__(self):
        self.download_dir = Path("files/podcasts")
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.ai = AIService()

    async def _get_feed_url(self, session: aiohttp.ClientSession, api_url: str) -> Optional[Tuple[str, str]]:
        """Fetch feed URL from iTunes API."""
        try:
            async with session.get(api_url) as resp:
                if resp.status != 200:
                    logger.warning(f"Failed to lookup podcast: {api_url} ({resp.status})")
                    return None
                text = await resp.text()
                data = json.loads(text)
                if data["resultCount"] > 0:
                    feed_url = data["results"][0]["feedUrl"]
                    collection_name = data["results"][0]["collectionName"]
                    return collection_name, feed_url
                return None
        except Exception as e:
            logger.error(f"Error fetching feed URL {api_url}: {e}")
            return None

    async def _download_mp3(self, session: aiohttp.ClientSession, url: str, filename: str) -> Optional[Path]:
        """Download MP3 file."""
        try:
            filepath = self.download_dir / filename
            if filepath.exists():
                logger.info(f"File already exists: {filename}")
                return filepath

            async with session.get(url) as resp:
                resp.raise_for_status()
                async with aiofiles.open(filepath, 'wb') as f:
                    await f.write(await resp.read())
            
            logger.info(f"Downloaded: {filename}")
            return filepath
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return None

    def _check_db_history(self, host: str, title: str) -> bool:
        """Check if episode exists in DB."""
        with Session(engine) as session:
            existing = session.exec(select(Podcast).where(Podcast.host == host, Podcast.title == title)).first()
            return existing is not None

    def _save_to_db(self, host: str, title: str, url: str = None):
        """Save episode to DB."""
        with Session(engine) as session:
            podcast = Podcast(host=host, title=title, url=url)
            session.add(podcast)
            session.commit()
            logger.info(f"Saved to DB: {host} - {title}")

    async def process_feed(self, session: aiohttp.ClientSession, podcast_name: str, feed_url: str) -> Optional[Path]:
        """Process a single feed: return path to summary markdown file if new."""
        try:
            feed = feedparser.parse(feed_url)
            if not feed.entries:
                return None

            entry = feed.entries[0] # Get latest episode
            title = entry.title.replace(" ", "_").replace("/", "_")
            
            # 1. Check DB first
            if self._check_db_history(podcast_name, title):
                logger.debug(f"Skipping already processed: {podcast_name} - {title}")
                return None

            enclosure = entry.get("enclosures") or []
            if not enclosure:
                return None
            
            mp3_url = enclosure[0].get("href")
            if not mp3_url:
                return None
            
            filename = f"{podcast_name}_{title}.mp3"
            
            # 2. Download
            filepath = await self._download_mp3(session, mp3_url, filename)
            if not filepath:
                return None
            
            # 3. AI Analysis
            logger.info(f"Analyzing {podcast_name} - {title}...")
            condition = "請幫我總結這集 Podcast 的重點內容，包含重要觀點與數據，使用繁體中文。"
            prompt = f"{condition}\n\nTitle: {title}\nHost: {podcast_name}"
            
            summary = await self.ai.call(RequestType.AUDIO, contents=filepath, prompt=prompt)
            
            # 4. Save Summary to File
            summary_filename = f"{podcast_name}_{title}.md"
            summary_path = self.download_dir / summary_filename
            
            content = f"# 🎙️ {podcast_name}\n## {title}\n\n{summary}\n\n[Original Audio]({mp3_url})"
            async with aiofiles.open(summary_path, "w", encoding="utf-8") as f:
                await f.write(content)

            # 5. Cleanup audio
            try:
                os.remove(filepath)
            except OSError as e:
                logger.warning(f"Failed to remove temp audio file {filepath}: {e}")
            
            # 6. Save DB History happens AFTER successful processing?
            # Or should scheduler handle it?
            # Better here to ensure atomicity of "processed".
            # But if sending fails? Maybe caller should save DB?
            # Let's save here. If sending fails, we at least analyzed it.
            # But user wants notification. If we save here and send fails, we never resend.
            # Let's return (Path, host, title) tuple so Caller can save DB after sending?
            # Complexity trade-off. Let's save DB *after* returning. Caller handles DB add.
            
            return summary_path, podcast_name, title, mp3_url

        except Exception as e:
            logger.error(f"Error processing feed {feed_url}: {e}")
            return None



    async def process_daily_podcasts(self) -> List[Tuple[Path, str, str, str]]:
        """Main process. Returns list of (md_path, host, title, url)."""
        logger.info("Starting Podcast Polling...")
        ids = settings.PODCAST_SOURCE_IDS
        lookup_base = settings.PODCAST_LOOKUP_URL
        
        results = []
        
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        
        timeout = aiohttp.ClientTimeout(total=300) # 5 minutes for podcasts
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            tasks = [self._get_feed_url(session, f"{lookup_base}{pid}") for pid in ids]
            feeds_info = await asyncio.gather(*tasks)
            feeds_info = [f for f in feeds_info if f]
            
            for name, url in feeds_info:
                # Sequential processing to respect rate limits
                res = await self.process_feed(session, name, url)
                if res:
                    results.append(res)
                
                # Sleep a bit to be nice to API
                await asyncio.sleep(5)
                
        return results

    def mark_as_processed(self, host: str, title: str, url: str):
        self._save_to_db(host, title, url)

