from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
from googletrans import Translator
from langdetect import detect
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Your YouTube API Keys
API_KEYS = [
    "AIzaSyDMNPDf4ShMb6Y8TDcNC9SYNNePPj_wPGw",
    "AIzaSyBAXPZUN8imEBIYXBCL0r3eIW7Dyz56uZw",
    "AIzaSyB9UmH-8pKtZIiwf8VFx6LjU6e6-eOpNes",
    "AIzaSyBFwL_u9agG5IjNWkR4kQ-rQjUi8BFme1k"
]

# Quota costs per API call type
QUOTA_COSTS = {
    "search": 100,
    "videos": 1,
    "channels": 1,
    "commentThreads": 1,
    "comments": 1
}

# Default daily quota per key (10,000 units)
DAILY_QUOTA = 10000

class YouTubeScraper:
    def __init__(self):
        self.lock = Lock()  # Initialize lock for thread safety
        self.api_keys = API_KEYS
        self.quota_usage = {key: {"usage": 0, "last_reset": datetime.now().date()} for key in API_KEYS}
        self.translator = Translator()

    def reset_quota_if_needed(self):
        """Reset quota usage for all keys if a new day has started."""
        today = datetime.now().date()
        with self.lock:
            for key in self.quota_usage:
                if self.quota_usage[key]["last_reset"] != today:
                    self.quota_usage[key]["usage"] = 0
                    self.quota_usage[key]["last_reset"] = today
                    logger.info(f"Quota reset for key {key} on {today}")

    def get_available_key(self, required_units=1):
        """Select an API key with sufficient remaining quota."""
        self.reset_quota_if_needed()
        with self.lock:
            for key in self.api_keys:
                remaining = DAILY_QUOTA - self.quota_usage[key]["usage"]
                if remaining >= required_units:
                    return key
            raise Exception("All API keys have exceeded their quota limit for today")

    def update_quota_usage(self, key, call_type):
        """Update quota usage for the given key and call type (thread-safe)."""
        units = QUOTA_COSTS.get(call_type, 1)
        with self.lock:
            self.quota_usage[key]["usage"] += units
            logger.info(f"Key {key} used {units} units for {call_type}. Total usage: {self.quota_usage[key]['usage']}")

    def build_service(self, key):
        """Build YouTube service with the given API key."""
        return build('youtube', 'v3', developerKey=key)

    def fetch_youtube_videos(self, query, max_results=5, max_limit=5, published_after=None):
        """Fetch YouTube videos concurrently, ensuring max_limit videos have transcripts."""
        try:
            key = self.get_available_key(QUOTA_COSTS["search"])
            youtube = self.build_service(key)
            response = youtube.search().list(
                part="snippet",
                q=query,
                type="video",
                maxResults=max_results,
                order="viewCount",
                publishedAfter=published_after
            ).execute()
            self.update_quota_usage(key, "search")
            video_ids = [item["id"]["videoId"] for item in response.get("items", [])]

            # Fetch video data concurrently
            videos = []
            complete_videos = 0
            with ThreadPoolExecutor(max_workers=3) as executor:
                future_to_video = {
                    executor.submit(self.fetch_video_data, video_id): video_id 
                    for video_id in video_ids
                }
                for future in as_completed(future_to_video):
                    video_data = future.result()
                    if video_data and video_data["transcript"] != "Transcript not available.":
                        videos.append(video_data)
                        complete_videos += 1
                        if complete_videos >= max_limit:
                            break
            return videos
        except Exception as e:
            logger.error(f"Error fetching videos for '{query}': {str(e)}")
            return []

    def fetch_video_data(self, video_id):
        """Fetch video data only if transcript is available."""
        try:
            # First check transcript availability (no quota cost)
            transcript = self.get_transcript(video_id)
            if transcript == "Transcript not available.":
                logger.info(f"Skipping video {video_id}: No transcript available.")
                return None

            # Proceed with fetching video data
            key = self.get_available_key(QUOTA_COSTS["videos"])
            youtube = self.build_service(key)
            video_response = youtube.videos().list(
                part="snippet,statistics",
                id=video_id
            ).execute()
            self.update_quota_usage(key, "videos")
            if not video_response["items"]:
                return None
            snippet = video_response["items"][0]["snippet"]
            stats = video_response["items"][0]["statistics"]

            # Channel details
            channel_id = snippet["channelId"]
            channel_details = self.fetch_channel_details(channel_id)

            # Fetch comments
            comments = self.fetch_comments(video_id, max_comments=15)

            return {
                "title": snippet["title"],
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "views": stats.get("viewCount", "0"),
                "likes": stats.get("likeCount", "0"),
                "published_at": snippet["publishedAt"],
                "channel_title": snippet["channelTitle"],
                "channel_creation_date": channel_details["creation_date"],
                "subscribers": channel_details["subscribers"],
                "transcript": transcript,
                "comments": comments
            }
        except Exception as e:
            logger.error(f"Error fetching data for video '{video_id}': {str(e)}")
            return None

    def fetch_channel_details(self, channel_id):
        """Fetch channel details with quota management."""
        try:
            key = self.get_available_key(QUOTA_COSTS["channels"])
            youtube = self.build_service(key)
            response = youtube.channels().list(
                part="snippet,statistics",
                id=channel_id
            ).execute()
            self.update_quota_usage(key, "channels")
            if not response["items"]:
                return {"creation_date": "Unknown", "subscribers": 0}
            snippet = response["items"][0]["snippet"]
            stats = response["items"][0]["statistics"]
            return {
                "creation_date": snippet["publishedAt"],
                "subscribers": stats.get("subscriberCount", 0)
            }
        except HttpError as e:
            logger.error(f"API error fetching channel details for '{channel_id}': {str(e)}")
            return {"creation_date": "Unknown", "subscribers": 0}
        except Exception as e:
            logger.error(f"Error fetching channel details for '{channel_id}': {str(e)}")
            return {"creation_date": "Unknown", "subscribers": 0}

    def get_transcript(self, video_id):
        """Fetch and translate transcript (no quota impact)."""
        try:
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
            full_text = " ".join([entry["text"] for entry in transcript])
            lang = detect(full_text)
            if lang != 'en':
                translated = self.translator.translate(full_text, dest='en').text
                return translated
            return full_text
        except (NoTranscriptFound, TranscriptsDisabled):
            return "Transcript not available."
        except Exception as e:
            logger.error(f"Error fetching transcript for '{video_id}': {str(e)}")
            return "Transcript not available."

    def fetch_comments(self, video_id, max_comments=15):
        """Fetch up to 15 comments concurrently, sorted by engagement."""
        try:
            all_comments = []
            next_page_token = None
            while len(all_comments) < max_comments * 2:
                key = self.get_available_key(QUOTA_COSTS["commentThreads"])
                youtube = self.build_service(key)
                response = youtube.commentThreads().list(
                    part="snippet",
                    videoId=video_id,
                    maxResults=100,
                    pageToken=next_page_token
                ).execute()
                self.update_quota_usage(key, "commentThreads")
                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_comment = {
                        executor.submit(self.process_comment, item): item 
                        for item in response["items"]
                    }
                    for future in as_completed(future_to_comment):
                        comment_data = future.result()
                        if comment_data:
                            all_comments.append(comment_data)
                next_page_token = response.get("nextPageToken")
                if not next_page_token:
                    break

            # Filter and sort
            filtered_comments = [c for c in all_comments if len(c["comment"].split()) > 5]
            sorted_comments = sorted(filtered_comments, key=lambda x: x["likes"], reverse=True)
            return sorted_comments[:max_comments]
        except Exception as e:
            logger.error(f"Error fetching comments for '{video_id}': {str(e)}")
            return []

    def process_comment(self, item):
        try:
            thread_id = item["id"]
            top_comment = item["snippet"]["topLevelComment"]["snippet"]
            subcomments = self.fetch_subcomments(thread_id)
            return {
                "author": top_comment["authorDisplayName"],
                "comment": top_comment["textDisplay"],
                "published_at": top_comment["publishedAt"],
                "likes": top_comment["likeCount"],
                "subcomments": subcomments
            }
        except Exception as e:
            logger.error(f"Error processing comment: {str(e)}")
            return None

    def fetch_subcomments(self, parent_id, max_subcomments=100):
        """Fetch subcomments with quota management."""
        subcomments_data = []
        try:
            key = self.get_available_key(QUOTA_COSTS["comments"])
            youtube = self.build_service(key)
            next_page_token = None
            while True:
                subcomments = youtube.comments().list(
                    part='snippet',
                    parentId=parent_id,
                    textFormat='plainText',
                    maxResults=100,
                    pageToken=next_page_token
                ).execute()
                self.update_quota_usage(key, "comments")
                for item in subcomments['items']:
                    subcomment = item['snippet']
                    subcomments_data.append({
                        'author': subcomment['authorDisplayName'],
                        'comment': subcomment['textDisplay'],
                        'published_at': subcomment['publishedAt'],
                        'likes': subcomment['likeCount']
                    })
                next_page_token = subcomments.get('nextPageToken')
                if not next_page_token or len(subcomments_data) >= max_subcomments:
                    break
                key = self.get_available_key(QUOTA_COSTS["comments"])
                youtube = self.build_service(key)
            return subcomments_data
        except HttpError as e:
            logger.error(f"API error fetching subcomments for parent '{parent_id}': {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Error fetching subcomments for parent '{parent_id}': {str(e)}")
            return []