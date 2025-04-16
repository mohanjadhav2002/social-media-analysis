# reddit.py
import praw
import logging
from collections import Counter
import re
import nltk
from nltk.corpus import stopwords
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

nltk.download('stopwords')

class RedditScraper:
    def __init__(self):
        self.reddit = praw.Reddit(
            client_id="ENTER_YOUR_ID",
            client_secret="ENTER_YOUR_SECRET",
            user_agent="project by u/YOUR_REDDIT_USERNAME",
            username="YOUR_REDDIT_USERNAME",
            password="YOUR_REDDIT_ACCOUNT_PASSWORD"
        )

    def rate_limit(self):
        time.sleep(1)

    def search_political_subreddits(self, query, limit=10):
        try:
            subreddit_results = list(self.reddit.subreddits.search(query, limit=limit))
            return [sub.display_name for sub in subreddit_results]
        except Exception as e:
            logger.error(f"Error searching subreddits for '{query}': {str(e)}")
            return []

    def get_post_data(self, post, num_comments=10, num_subcomments=5):
        try:
            # Only proceed if selftext is non-empty
            if not post.selftext or post.selftext.strip() == "":
                logger.info(f"Skipping post {post.id}: No selftext available.")
                return None

            post_data = {
                "title": post.title,
                "url": post.url,
                "score": post.score,
                "comments_count": post.num_comments,
                "author": post.author.name if post.author else "Unknown",
                "created_utc": post.created_utc,
                "selftext": post.selftext,
                "comments": []
            }
            post.comments.replace_more(limit=0)
            top_comments = sorted(post.comments, key=lambda c: c.score, reverse=True)[:num_comments]
            for comment in top_comments:
                comment.replies.replace_more(limit=None)
                comment_data = {
                    "author": comment.author.name if comment.author else "Unknown",
                    "comment": comment.body,
                    "published_at": comment.created_utc,
                    "likes": comment.score,
                    "subcomments": []
                }
                subcomments = sorted(comment.replies, key=lambda r: r.score, reverse=True)[:num_subcomments]
                for subcomment in subcomments:
                    subcomment_data = {
                        "author": subcomment.author.name if subcomment.author else "Unknown",
                        "comment": subcomment.body,
                        "published_at": subcomment.created_utc,
                        "likes": subcomment.score
                    }
                    comment_data["subcomments"].append(subcomment_data)
                post_data["comments"].append(comment_data)
            return post_data
        except Exception as e:
            logger.error(f"Error fetching data for post '{post.id}': {str(e)}")
            return None

    def fetch_reddit_posts(self, subreddits, limit_per_sub=15, num_comments=10, num_subcomments=5):
        posts = []
        seen_urls = set()  # For deduplication
        for sub in subreddits:
            try:
                self.rate_limit()
                posts_batch = list(self.reddit.subreddit(sub).hot(limit=limit_per_sub))
                for post in posts_batch:
                    self.rate_limit()
                    if post.url not in seen_urls and post.selftext and post.selftext.strip() != "":
                        post_data = self.get_post_data(post, num_comments, num_subcomments)
                        if post_data:  # Only append if post_data is not None
                            posts.append(post_data)
                            seen_urls.add(post.url)
            except Exception as e:
                logger.error(f"Could not fetch posts from subreddit {sub}: {str(e)}")
        return posts

    def extract_topics(self, posts, top_n=15):
        try:
            stop_words = set(stopwords.words('english'))
            words = []
            for post in posts:
                text = post.get('title', '') + " " + post.get('selftext', '')
                tokens = re.findall(r'\b(?!https?://)\w{4,}\b', text.lower())
                tokens = [token for token in tokens if token not in stop_words and not token.startswith('http')]
                words.extend(tokens)
            freq = Counter(words)
            return [word for word, count in freq.most_common(top_n)]
        except Exception as e:
            logger.error(f"Error extracting topics: {str(e)}")
            return []

    def gather_posts_for_topic(self, topic, subreddits, limit=15, num_comments=10, num_subcomments=5):
        posts = []
        seen_urls = set()  # For deduplication
        for sub in subreddits:
            try:
                self.rate_limit()
                posts_batch = list(self.reddit.subreddit(sub).search(
                    query=topic,
                    sort='hot',
                    limit=limit,
                    time_filter='month'
                ))
                for post in posts_batch:
                    self.rate_limit()
                    if post.url not in seen_urls and post.selftext and post.selftext.strip() != "":
                        post_data = self.get_post_data(post, num_comments, num_subcomments)
                        if post_data:  # Only append if post_data is not None
                            posts.append(post_data)
                            seen_urls.add(post.url)
                    if len(posts) >= limit:
                        break
            except Exception as e:
                logger.error(f"Error fetching posts for topic '{topic}' in '{sub}': {str(e)}")
        return posts[:limit]
