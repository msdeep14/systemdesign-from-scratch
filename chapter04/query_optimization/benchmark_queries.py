#!/usr/bin/env python3
"""
Benchmark the PhotoZ application queries to expose N+1 problems and missing indexes.

This script replicates the exact query patterns from views.py and templates,
counts SQL queries per operation, and runs EXPLAIN ANALYZE on key queries.

Requires: Seeded database (run seed_data.py first)
"""

import sys
import os
import time

PHOTOZ_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'photoz')
sys.path.insert(0, PHOTOZ_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bses.settings')
os.environ.setdefault('POSTGRES_HOST', 'localhost')

import django
django.setup()

# Force DEBUG=True so connection.queries captures all SQL
from django.conf import settings
settings.DEBUG = True

from django.db import connection, reset_queries
from django.db.models import Q, Count
from django.core.paginator import Paginator
from django.contrib.auth.models import User
from users.models import UserProfile, Follow
from photos.models import Photo, Like, Comment
from communities.models import Community, CommunityMembership
from notifications.models import Notification


def print_header(title, subtitle=""):
    print("\n" + "=" * 70)
    print(f"  {title}")
    if subtitle:
        print(f"  {subtitle}")
    print("=" * 70)


def print_queries(queries, show_all=False, max_display=15):
    total_db_time = sum(float(q['time']) for q in queries)
    print(f"\n  SQL queries fired: {len(queries)}")
    print(f"  Total DB time: {total_db_time * 1000:.1f}ms")
    print(f"\n  Query breakdown:")
    print("  " + "-" * 66)

    display_count = len(queries) if show_all else min(max_display, len(queries))
    for i, q in enumerate(queries[:display_count]):
        sql = q['sql'].replace('"', '')
        # Truncate long queries for readability
        if len(sql) > 120:
            sql = sql[:117] + "..."
        print(f"   #{i+1:<3} [{float(q['time'])*1000:6.1f}ms]  {sql}")

    if not show_all and len(queries) > max_display:
        remaining = len(queries) - max_display
        print(f"\n   ... and {remaining} more queries (use --verbose to see all)")

    print("  " + "-" * 66)


def run_explain_analyze(queryset, label="Main query"):
    """Run EXPLAIN ANALYZE on a queryset's SQL."""
    compiler = queryset.query.get_compiler(using='default')
    sql, params = compiler.as_sql()

    print(f"\n  EXPLAIN ANALYZE -- {label}:")
    print("  " + "-" * 66)

    with connection.cursor() as cursor:
        cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS) {sql}", params)
        rows = cursor.fetchall()
        for row in rows:
            print(f"   {row[0]}")

    print("  " + "-" * 66)


def pick_benchmark_user():
    """Find a user who follows many people (worst case for newsfeed)."""
    heavy_user = (
        User.objects
        .annotate(follow_count=Count('following'))
        .order_by('-follow_count')
        .first()
    )
    if not heavy_user:
        print("  ERROR: No users found. Run seed_data.py first.")
        sys.exit(1)

    follow_count = Follow.objects.filter(follower=heavy_user).count()
    community_count = CommunityMembership.objects.filter(
        user=heavy_user, status='accepted'
    ).count()
    notification_count = Notification.objects.filter(recipient=heavy_user).count()

    print(f"\n  Benchmark user: {heavy_user.profile.username_display}")
    print(f"     Follows: {follow_count} users")
    print(f"     Communities: {community_count}")
    print(f"     Notifications: {notification_count}")

    return heavy_user


def benchmark_newsfeed(user, verbose=False):
    """
    Replicates the exact code path from newsfeed/views.py + feed.html template.
    This is where the worst N+1 problem lives.
    """
    print_header(
        "BENCHMARK 1: Newsfeed Page Load",
        "(replicates newsfeed/views.py + feed.html template rendering)"
    )

    reset_queries()
    start = time.time()

    # === views.py code (line 12-25) ===
    followed_users = Follow.objects.filter(
        follower=user
    ).values_list('following', flat=True)

    my_communities = CommunityMembership.objects.filter(
        user=user, status='accepted'
    ).values_list('community', flat=True)

    feed = Photo.objects.filter(
        Q(user__in=followed_users, community__isnull=True) |
        Q(community__in=my_communities) |
        Q(user=user)
    ).order_by('-created_at').distinct()

    paginator = Paginator(feed, 20)
    page_obj = paginator.get_page(1)

    liked_photo_ids = set(user.like_set.values_list('photo_id', flat=True))

    # === feed.html template access (the N+1 explosion) ===
    # Each of these attribute accesses triggers a lazy DB query per photo
    for photo in page_obj:
        # Line 13-14: photo.user.profile.profile_picture
        _ = photo.user.profile.profile_picture
        # Line 17: photo.user.profile.first_name
        _ = photo.user.profile.first_name
        # Line 22-23: photo.user.profile.username_display, last_name
        _ = photo.user.profile.username_display
        _ = photo.user.profile.last_name
        # Line 26: photo.community (ForeignKey lazy load)
        _ = photo.community
        if photo.community:
            _ = photo.community.name
        # Line 40: photo.likes.count()
        _ = photo.likes.count()
        # Line 43: photo.comments.count()
        _ = photo.comments.count()
        # Line 49: photo.user.profile.username_display (again, but cached)
        _ = photo.user.profile.username_display

    elapsed = time.time() - start
    queries = list(connection.queries)

    print(f"\n  Wall time: {elapsed*1000:.0f}ms")
    print_queries(queries, show_all=verbose)

    # Categorize the queries
    user_queries = sum(1 for q in queries if 'auth_user' in q['sql'] and 'SELECT' in q['sql'])
    profile_queries = sum(1 for q in queries if 'users_userprofile' in q['sql'] and 'SELECT' in q['sql'])
    like_count_queries = sum(1 for q in queries if 'photos_like' in q['sql'] and 'COUNT' in q['sql'])
    comment_count_queries = sum(1 for q in queries if 'photos_comment' in q['sql'] and 'COUNT' in q['sql'])
    community_queries = sum(1 for q in queries if 'communities_community' in q['sql'] and 'SELECT' in q['sql'] and 'membership' not in q['sql'])

    print(f"\n  Query breakdown by type:")
    print(f"     Base queries (feed, follows, communities, likes):  ~5")
    print(f"     User lookups (N+1 per photo):       {user_queries}")
    print(f"     Profile lookups (N+1 per photo):    {profile_queries}")
    print(f"     Community lookups (N+1 per photo):  {community_queries}")
    print(f"     Like COUNT (N+1 per photo):         {like_count_queries}")
    print(f"     Comment COUNT (N+1 per photo):      {comment_count_queries}")
    print(f"     -----------------------------------------")
    print(f"     TOTAL:                              {len(queries)}")

    # EXPLAIN ANALYZE on the main feed query
    feed_qs = Photo.objects.filter(
        Q(user__in=followed_users, community__isnull=True) |
        Q(community__in=my_communities) |
        Q(user=user)
    ).order_by('-created_at').distinct()[:20]

    run_explain_analyze(feed_qs, "Newsfeed main query (top 20 photos)")

    return len(queries)


def benchmark_profile(user, verbose=False):
    """
    Replicates users/views.py profile_view (line 80-100).
    """
    print_header(
        "BENCHMARK 2: Profile Page",
        "(replicates users/views.py profile_view)"
    )

    # Pick a different user's profile to view (one with many photos)
    target_profile = (
        UserProfile.objects
        .annotate(photo_count=Count('user__photos'))
        .order_by('-photo_count')
        .first()
    )

    reset_queries()
    start = time.time()

    # === views.py code (line 80-100) ===
    profile = UserProfile.objects.get(username_display=target_profile.username_display)
    user_obj = profile.user

    photos = user_obj.photos.filter(community__isnull=True).order_by('-created_at')

    followers_count = user_obj.followers.count()
    following_count = user_obj.following.count()

    is_following = Follow.objects.filter(follower=user, following=user_obj).exists()

    # Force evaluate the photos queryset (template iteration)
    for photo in photos:
        _ = photo.likes.count()
        _ = photo.comments.count()
        _ = photo.image.url
        _ = photo.caption

    elapsed = time.time() - start
    queries = list(connection.queries)

    photo_count = photos.count()

    print(f"\n  Viewing profile: {target_profile.username_display} ({photo_count} photos)")
    print(f"  Wall time: {elapsed*1000:.0f}ms")
    print_queries(queries, show_all=verbose)

    # EXPLAIN ANALYZE
    run_explain_analyze(photos, "Profile photos query")

    return len(queries)


def benchmark_search(verbose=False):
    """
    Replicates users/views.py search_users_view (line 172-183).
    Shows lack of text search indexes.
    """
    print_header(
        "BENCHMARK 3: User Search",
        "(replicates users/views.py search_users_view)"
    )

    reset_queries()
    start = time.time()

    # Search for a common name fragment
    query = 'alex'
    results = UserProfile.objects.filter(
        Q(username_display__icontains=query) |
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query)
    )
    result_count = results.count()
    result_list = list(results[:20])

    elapsed = time.time() - start
    queries = list(connection.queries)

    print(f"\n  Search query: '{query}' -> {result_count} results")
    print(f"  Wall time: {elapsed*1000:.0f}ms")
    print_queries(queries, show_all=verbose)

    # EXPLAIN ANALYZE on the search query
    run_explain_analyze(results, f"User search for '{query}'")

    return len(queries)


def benchmark_notification_count(user, verbose=False):
    """
    Replicates notifications/context_processors.py unread_count.
    This runs on EVERY SINGLE page load for authenticated users.
    """
    print_header(
        "BENCHMARK 4: Unread Notification Count (Context Processor)",
        "(runs on EVERY page load -- notifications/context_processors.py)"
    )

    reset_queries()
    start = time.time()

    # === context_processors.py code ===
    unread_count = user.notifications.filter(is_read=False).count()

    elapsed = time.time() - start
    queries = list(connection.queries)

    print(f"\n  Unread count: {unread_count}")
    print(f"  Wall time: {elapsed*1000:.0f}ms")
    print_queries(queries, show_all=verbose)

    # EXPLAIN ANALYZE
    notif_qs = Notification.objects.filter(recipient=user, is_read=False)
    run_explain_analyze(notif_qs, "Unread notification count")

    return len(queries)


def benchmark_photo_detail(user, verbose=False):
    """
    Replicates photos/views.py photo_detail (line 46-57).
    """
    print_header(
        "BENCHMARK 5: Photo Detail Page",
        "(replicates photos/views.py photo_detail)"
    )

    # Pick a photo with many comments
    photo = Photo.objects.annotate(c=Count('comments')).order_by('-c').first()

    reset_queries()
    start = time.time()

    # === views.py code ===
    photo = Photo.objects.get(id=photo.id)
    likes_count = photo.likes.count()
    has_liked = photo.likes.filter(user=user).exists()
    comments = photo.comments.all().order_by('created_at')

    # Template access
    _ = photo.user.profile.first_name
    _ = photo.user.profile.profile_picture
    _ = photo.image.url

    for comment in comments:
        _ = comment.user.profile.first_name
        _ = comment.user.profile.username_display

    elapsed = time.time() - start
    queries = list(connection.queries)

    print(f"\n  Photo {photo.id}: {likes_count} likes, {comments.count()} comments")
    print(f"  Wall time: {elapsed*1000:.0f}ms")
    print_queries(queries, show_all=verbose)

    # EXPLAIN ANALYZE
    run_explain_analyze(photo.comments.all().order_by('created_at'), "Photo comments query")

    return len(queries)


def print_summary(results):
    print("\n")
    print("=" * 70)
    print("  SUMMARY: Query Count Per Operation (BEFORE optimization)")
    print("=" * 70)
    print(f"  {'Operation':<45} {'Queries':>10}")
    print("  " + "-" * 58)
    total = 0
    for label, count in results:
        print(f"  {label:<45} {count:>10}")
        total += count
    print("  " + "-" * 58)
    print(f"  {'TOTAL (a single user browsing 5 pages)':<45} {total:>10}")
    print()
    print("  This means a single user session fires ~{} SQL queries.".format(total))
    print("     With 100 concurrent users, that's ~{} queries hitting Postgres.".format(total * 100))
    print()
    print("  The main culprits:")
    print("     1. N+1 queries: no select_related / prefetch_related")
    print("     2. COUNT(*) per photo: no annotation")
    print("     3. Missing indexes: sequential scans on large tables")
    print("     4. Context processor: unread count on every page load")
    print("=" * 70 + "\n")


def main():
    verbose = '--verbose' in sys.argv

    print("\n" + "=" * 70)
    print("  PhotoZ Query Benchmark -- Chapter 04 (BEFORE optimization)")
    print("=" * 70)

    # Check data exists
    if User.objects.count() < 50:
        print("\n  ERROR: Database has too few users. Run seed_data.py first.")
        sys.exit(1)

    user = pick_benchmark_user()

    results = []
    results.append(("Newsfeed page load", benchmark_newsfeed(user, verbose)))
    results.append(("Profile page", benchmark_profile(user, verbose)))
    results.append(("User search", benchmark_search(verbose)))
    results.append(("Unread notification count (per page)", benchmark_notification_count(user, verbose)))
    results.append(("Photo detail page", benchmark_photo_detail(user, verbose)))

    print_summary(results)


if __name__ == '__main__':
    main()
