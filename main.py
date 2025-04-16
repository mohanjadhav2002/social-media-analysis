import streamlit as st
import json
from reddit import RedditScraper
from app import YouTubeScraper
from collections import Counter
import re
import nltk
from nltk.corpus import stopwords
from datetime import datetime, timedelta
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Download stopwords
nltk.download('stopwords')

def extract_topics(text_list, top_n=10):
    """Extract trending topics from a list of texts (Reddit posts or YouTube titles)."""
    stop_words = set(stopwords.words('english'))
    words = []
    for text in text_list:
        if isinstance(text, dict):
            text = text.get('title', '')
        tokens = re.findall(r'\w+', text.lower())
        tokens = [token for token in tokens if token not in stop_words and len(token) > 3]
        words.extend(tokens)
    freq = Counter(words)
    return [word for word, count in freq.most_common(top_n)]

def find_common_topics(reddit_topics, youtube_topics):
    """Find common trending topics between Reddit and YouTube."""
    return list(set(reddit_topics).intersection(set(youtube_topics)))

def main():
    st.title("Trending Topics Across Social Media")
    query = st.text_input("Enter topics (comma-separated, e.g., Indian politics, BJP):")
    time_frame = st.selectbox("Select YouTube time frame:", ["Last 1 month", "Last 3 months", "Last 6 months", "Last 1 year"])

    if st.button("Search"):
        try:
            topics = [topic.strip() for topic in query.split(',')]
            reddit_scraper = RedditScraper()
            youtube_scraper = YouTubeScraper()

            # Calculate YouTube date filter
            if time_frame == "Last 1 month":
                published_after = (datetime.now() - timedelta(days=30)).isoformat() + "Z"
            elif time_frame == "Last 3 months":
                published_after = (datetime.now() - timedelta(days=90)).isoformat() + "Z"
            elif time_frame == "Last 6 months":
                published_after = (datetime.now() - timedelta(days=180)).isoformat() + "Z"
            else:
                published_after = (datetime.now() - timedelta(days=365)).isoformat() + "Z"

            # Gather Reddit data
            all_subreddits = set()
            for topic in topics:
                subreddits = reddit_scraper.search_political_subreddits(topic, limit=10)
                all_subreddits.update(subreddits)
            st.write("Subreddits Found:", list(all_subreddits))

            reddit_posts = reddit_scraper.fetch_reddit_posts(list(all_subreddits), limit_per_sub=15)
            reddit_topics = reddit_scraper.extract_topics(reddit_posts, top_n=15)
            st.write("Reddit Trending Topics:", reddit_topics)

            # Gather YouTube data with error handling
            youtube_videos = []
            youtube_topics = []
            try:
                for topic in topics:
                    videos = youtube_scraper.fetch_youtube_videos(topic, max_results=10, published_after=published_after)
                    youtube_videos.extend(videos)
                youtube_topics = extract_topics(youtube_videos, top_n=10)
                st.write("YouTube Trending Topics:", youtube_topics)
            except Exception as e:
                logger.error(f"Error fetching YouTube data: {str(e)}")
                st.write("YouTube API quota exhausted or error occurred. Proceeding with Reddit data only.")

            # Find common topics
            common_topics = find_common_topics(reddit_topics, youtube_topics)
            st.write("Common Trending Topics:", common_topics)

            # Gather info for topics
            all_topic_info = []
            if common_topics:
                # Case 1: Common topics exist
                for topic in common_topics:
                    reddit_posts_for_topic = reddit_scraper.gather_posts_for_topic(topic, list(all_subreddits), limit=15)
                    youtube_videos_for_topic = []
                    if youtube_topics:  # Only try YouTube if we have data
                        youtube_videos_for_topic = youtube_scraper.fetch_youtube_videos(topic, max_results=10, published_after=published_after)
                    topic_info = {
                        "topic": topic,
                        "reddit_posts": reddit_posts_for_topic,
                        "youtube_videos": youtube_videos_for_topic
                    }
                    all_topic_info.append(topic_info)
            else:
                # Case 2: No common topics or YouTube failed
                st.write("No common trending topics found or YouTube data unavailable. Gathering top 5 trending topics.")
                # Get top 5 Reddit topics
                top_reddit_topics = reddit_topics[:5]
                for topic in top_reddit_topics:
                    reddit_posts_for_topic = reddit_scraper.gather_posts_for_topic(topic, list(all_subreddits), limit=15)
                    topic_info = {
                        "topic": topic,
                        "reddit_posts": reddit_posts_for_topic,
                        "youtube_videos": []
                    }
                    all_topic_info.append(topic_info)
                # Get top 5 YouTube topics if available
                if youtube_topics:
                    top_youtube_topics = youtube_topics[:5]
                    for topic in top_youtube_topics:
                        youtube_videos_for_topic = youtube_scraper.fetch_youtube_videos(topic, max_results=10, published_after=published_after)
                        topic_info = {
                            "topic": topic,
                            "reddit_posts": [],
                            "youtube_videos": youtube_videos_for_topic
                        }
                        all_topic_info.append(topic_info)

            # Save to JSON
            with open("trending_topics_info.json", "w") as f:
                json.dump(all_topic_info, f, indent=4)
            st.write("Data scraped successfully and saved as JSON file")

        except Exception as e:
            logger.error(f"Error during search: {str(e)}")
            st.write("An error occurred. Check the logs.")

if __name__ == "__main__":
    main()
