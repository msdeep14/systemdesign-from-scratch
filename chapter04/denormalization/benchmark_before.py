#!/usr/bin/env python3
"""
Benchmark the current COUNT(*) approach for likes and comments before denormalization.

Measures three page scenarios that currently fire COUNT GROUP BY or COUNT(*) queries
to compute likes_count and comments_count at read time.

This is the BEFORE number. Run benchmark_after.py after the denormalization migration
to compare query counts and latencies.

Requires: seeded database (run chapter04/query_optimization/seed_data.py first)
"""

import os
import sys
import time

PHOTOZ_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "photoz"
)
sys.path.insert(0, PHOTOZ_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bses.settings")
os.environ.setdefault("POSTGRES_HOST", "localhost")

import django

django.setup()

from django.conf import settings

settings.DEBUG = True

from communities.models import CommunityMembership
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import connection, reset_queries
from django.db.models import Count, Q
from photos.models import Comment, Like, Photo
from users.models import Follow


def print_header(title, subtitle=""):
    print("\n" + "=" * 70)
    print(f"  {title}")
    if subtitle:
        print(f"  {subtitle}")
    print("=" * 70)


def count_queries_by_type(queries):
    return sum(1 for q in queries if "COUNT" in q["sql"])


def run_explain_analyze(sql, params, label):
    print(f"\n  EXPLAIN ANALYZE -- {label}:")
    print("  " + "-" * 66)
    with connection.cursor() as cursor:
        cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS) {sql}", params)
        for row in cursor.fetchall():
            print(f"   {row[0]}")
    print("  " + "-" * 66)


def pick_benchmark_user():
    user = (
        User.objects.annotate(follow_count=Count("following"))
        .order_by("-follow_count")
        .first()
    )
    if not user:
        print("  ERROR: No users found. Run seed_data.py first.")
        sys.exit(1)

    follow_count = Follow.objects.filter(follower=user).count()
    community_count = CommunityMembership.objects.filter(
        user=user, status="accepted"
    ).count()
    print(f"\n  Benchmark user: {user.profile.username_display}")
    print(f"    Follows: {follow_count} users")
    print(f"    Communities: {community_count}")
    return user


def benchmark_newsfeed(user, verbose=False):
    """
    Replicates the decoupled COUNT GROUP BY pattern in newsfeed/views.py lines 113-128.
    Fires 2 extra COUNT queries per page load (one for likes, one for comments).
    """
    print_header(
        "BENCHMARK 1: Newsfeed Page Load",
        "(replicates newsfeed/views.py decoupled COUNT GROUP BY -- lines 113-128)",
    )

    reset_queries()
    start = time.perf_counter()

    followed_users = Follow.objects.filter(follower=user).values_list(
        "following", flat=True
    )
    my_communities = CommunityMembership.objects.filter(
        user=user, status="accepted"
    ).values_list("community", flat=True)

    feed_qs = (
        Photo.objects.filter(
            Q(user__in=followed_users, community__isnull=True)
            | Q(community__in=my_communities)
            | Q(user=user)
        )
        .order_by("-created_at")
        .distinct()[:1000]
    )

    photo_ids = list(feed_qs.values_list("id", flat=True))

    paginator = Paginator(photo_ids, getattr(settings, "BSES_PAGE_SIZE", 20))
    page_obj = paginator.get_page(1)
    page_photo_ids = list(page_obj.object_list)

    photos_qs = Photo.objects.filter(id__in=page_photo_ids).select_related(
        "user__profile", "community"
    )
    photos_dict = {p.id: p for p in photos_qs}
    page_photos = [photos_dict[pid] for pid in page_photo_ids if pid in photos_dict]

    # Exact block from newsfeed/views.py that will be removed after denormalization.
    likes_counts = dict(
        Like.objects.filter(photo_id__in=page_photo_ids)
        .values("photo_id")
        .annotate(count=Count("id"))
        .values_list("photo_id", "count")
    )
    comments_counts = dict(
        Comment.objects.filter(photo_id__in=page_photo_ids)
        .values("photo_id")
        .annotate(count=Count("id"))
        .values_list("photo_id", "count")
    )
    for photo in page_photos:
        photo.likes_count = likes_counts.get(photo.id, 0)
        photo.comments_count = comments_counts.get(photo.id, 0)

    elapsed_ms = (time.perf_counter() - start) * 1000
    queries = list(connection.queries)
    total_db_ms = sum(float(q["time"]) for q in queries) * 1000
    count_q = count_queries_by_type(queries)

    print(f"\n  Photos on page: {len(page_photos)}")
    print(f"  Wall time:      {elapsed_ms:.1f}ms")
    print(f"  Total DB time:  {total_db_ms:.1f}ms")
    print(f"  SQL queries:    {len(queries)}")
    print(f"  COUNT queries:  {count_q}  <-- these go to 0 after denormalization")

    if verbose:
        likes_qs = (
            Like.objects.filter(photo_id__in=page_photo_ids)
            .values("photo_id")
            .annotate(count=Count("id"))
        )
        compiler = likes_qs.query.get_compiler(using="default")
        sql, params = compiler.as_sql()
        run_explain_analyze(
            sql, params, "likes COUNT GROUP BY (one of 2 count queries)"
        )

    return {
        "queries": len(queries),
        "count_queries": count_q,
        "wall_ms": elapsed_ms,
        "db_ms": total_db_ms,
    }


def benchmark_profile(user, verbose=False):
    """
    Replicates users/views.py profile page.
    Calls photo.likes.count() per photo -- an N+1 COUNT pattern.
    """
    print_header(
        "BENCHMARK 2: Profile Page",
        "(photo.likes.count() + photo.comments.count() per photo -- N+1 COUNT pattern)",
    )

    from users.models import UserProfile

    target_profile = (
        UserProfile.objects.annotate(photo_count=Count("user__photos"))
        .order_by("-photo_count")
        .first()
    )

    reset_queries()
    start = time.perf_counter()

    profile = UserProfile.objects.select_related("user").get(
        username_display=target_profile.username_display
    )
    user_obj = profile.user

    photos = list(
        user_obj.photos.filter(community__isnull=True).order_by("-created_at")[:20]
    )

    _ = user_obj.followers.count()
    _ = user_obj.following.count()
    _ = Follow.objects.filter(follower=user, following=user_obj).exists()

    # N+1 COUNT: one query per photo for each counter
    for photo in photos:
        _ = photo.likes.count()
        _ = photo.comments.count()

    elapsed_ms = (time.perf_counter() - start) * 1000
    queries = list(connection.queries)
    total_db_ms = sum(float(q["time"]) for q in queries) * 1000
    count_q = count_queries_by_type(queries)

    print(
        f"\n  Profile: {target_profile.username_display} ({len(photos)} photos shown)"
    )
    print(f"  Wall time:      {elapsed_ms:.1f}ms")
    print(f"  Total DB time:  {total_db_ms:.1f}ms")
    print(f"  SQL queries:    {len(queries)}")
    print(f"  COUNT queries:  {count_q}  ({len(photos)} photos x 2 counts each)")

    return {
        "queries": len(queries),
        "count_queries": count_q,
        "wall_ms": elapsed_ms,
        "db_ms": total_db_ms,
    }


def benchmark_photo_detail(user, verbose=False):
    """
    Replicates photos/views.py photo_detail -- line 80.
    Single photo.likes.count() call.
    """
    print_header(
        "BENCHMARK 3: Photo Detail Page",
        "(replicates photos/views.py photo_detail -- line 80)",
    )

    photo = Photo.objects.annotate(c=Count("comments")).order_by("-c").first()

    reset_queries()
    start = time.perf_counter()

    photo = Photo.objects.select_related("user__profile", "community").get(id=photo.id)

    # Single COUNT(*) to be replaced by reading photo.likes_count column directly.
    likes_count = photo.likes.count()
    has_liked = photo.likes.filter(user=user).exists()
    comments = list(
        photo.comments.select_related("user__profile").order_by("created_at")
    )

    _ = photo.user.profile.first_name
    _ = photo.user.profile.profile_picture

    elapsed_ms = (time.perf_counter() - start) * 1000
    queries = list(connection.queries)
    total_db_ms = sum(float(q["time"]) for q in queries) * 1000
    count_q = count_queries_by_type(queries)

    print(f"\n  Photo {photo.id}: {likes_count} likes, {len(comments)} comments")
    print(f"  Wall time:      {elapsed_ms:.1f}ms")
    print(f"  Total DB time:  {total_db_ms:.1f}ms")
    print(f"  SQL queries:    {len(queries)}")
    print(f"  COUNT queries:  {count_q}")

    if verbose:
        likes_qs = photo.likes.all()
        compiler = likes_qs.query.get_compiler(using="default")
        sql, params = compiler.as_sql()
        run_explain_analyze(
            f"SELECT COUNT(*) FROM ({sql}) subq", params, "photo.likes.count()"
        )

    return {
        "queries": len(queries),
        "count_queries": count_q,
        "wall_ms": elapsed_ms,
        "db_ms": total_db_ms,
    }


def print_summary(results):
    print("\n\n" + "=" * 70)
    print("  BEFORE DENORMALIZATION -- Baseline Results")
    print("  Run benchmark_after.py after the migration to compare.")
    print("=" * 70)
    print(
        f"  {'Scenario':<35} {'Queries':>8} {'COUNTs':>8} {'DB ms':>9} {'Wall ms':>9}"
    )
    print("  " + "-" * 70)
    for label, r in results:
        print(
            f"  {label:<35} {r['queries']:>8} {r['count_queries']:>8} "
            f"{r['db_ms']:>8.1f} {r['wall_ms']:>8.1f}"
        )
    print("  " + "-" * 70)
    total_count_q = sum(r["count_queries"] for _, r in results)
    print(f"\n  Total COUNT queries across all 3 scenarios: {total_count_q}")
    print("  After denormalization, this number should be 0.\n")
    print("=" * 70 + "\n")


def main():
    verbose = "--verbose" in sys.argv

    print("\n" + "=" * 70)
    print("  Photoz -- Denormalization Benchmark (BEFORE)")
    print("  Measures COUNT(*) query cost for likes and comments")
    print("=" * 70)

    if User.objects.count() < 50:
        print("\n  ERROR: Database has too few users. Run seed_data.py first.")
        sys.exit(1)

    user = pick_benchmark_user()

    results = []
    results.append(("Newsfeed page load", benchmark_newsfeed(user, verbose)))
    results.append(("Profile page (20 photos)", benchmark_profile(user, verbose)))
    results.append(("Photo detail page", benchmark_photo_detail(user, verbose)))

    print_summary(results)


if __name__ == "__main__":
    main()
