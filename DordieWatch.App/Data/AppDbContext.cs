using Microsoft.EntityFrameworkCore;

namespace DordieWatch.App.Data;

public sealed class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options)
{
    public DbSet<MediaItemEntity> MediaItems => Set<MediaItemEntity>();
    public DbSet<EpisodeEntity> Episodes => Set<EpisodeEntity>();
    public DbSet<WatchProgressEntity> WatchProgress => Set<WatchProgressEntity>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<MediaItemEntity>(entity =>
        {
            entity.HasIndex(x => x.FolderPath).IsUnique();
            entity.Property(x => x.Title).HasMaxLength(512);
            entity.Property(x => x.Category).HasMaxLength(32);
            entity.Property(x => x.FolderPath).HasMaxLength(2048);
            entity.Property(x => x.PreferredSubtitleLanguage).HasMaxLength(128);
        });

        modelBuilder.Entity<EpisodeEntity>(entity =>
        {
            entity.HasIndex(x => x.VideoPath).IsUnique();
            entity.Property(x => x.Title).HasMaxLength(512);
            entity.Property(x => x.VideoPath).HasMaxLength(2048);
            entity.Property(x => x.ExternalSubtitlePath).HasMaxLength(2048);
            entity.HasOne(x => x.MediaItem)
                .WithMany(x => x.Episodes)
                .HasForeignKey(x => x.MediaItemId)
                .OnDelete(DeleteBehavior.Cascade);
        });

        modelBuilder.Entity<WatchProgressEntity>(entity =>
        {
            entity.HasIndex(x => x.EpisodeId).IsUnique();
            entity.HasOne(x => x.Episode)
                .WithOne(x => x.Progress)
                .HasForeignKey<WatchProgressEntity>(x => x.EpisodeId)
                .OnDelete(DeleteBehavior.Cascade);
        });
    }
}
