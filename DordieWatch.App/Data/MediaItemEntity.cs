using DordieWatch.App.Models;
using System.Collections.Generic;

namespace DordieWatch.App.Data;

public sealed class MediaItemEntity
{
    public long Id { get; set; }
    public string Title { get; set; } = "";
    public MediaKind Kind { get; set; }
    public string Category { get; set; } = "anime";
    public string FolderPath { get; set; } = "";
    public string? PosterPath { get; set; }
    public string? BackdropPath { get; set; }
    public string WebsiteIdsJson { get; set; } = "[]";
    public DateTimeOffset UpdatedAt { get; set; }
    public List<EpisodeEntity> Episodes { get; set; } = [];
}
