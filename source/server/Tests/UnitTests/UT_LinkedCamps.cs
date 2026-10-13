using System.Collections.Generic;
using DOL.GS.HearthDAoC;
using DOL.GS.Quests;
using NUnit.Framework;

namespace DOL.GS.Tests;

// HearthDAoC (#119, owner 2026-10-13): a quest camp's members join a fight against whoever attacks one of its callers,
// as the period's linked camps did ("she is by the fire, linked to 2 rangers"; "if you pull a guard from next to the
// tower sir dillius will come too"). Who joins is decided here; the game wiring is LinkedCamps.OnAttacked.
[TestFixture]
public sealed class UT_LinkedCamps
{
    private static readonly ClassicQuests.LinkGroup Fire = new()
    {
        Name = "Delfina's fire", Members = ["delfina", "r1", "r2"], Callers = ["delfina"], Range = 1500,
    };

    private static readonly ClassicQuests.LinkGroup Tower = new()
    {
        Name = "Sir Dillus's tower", Members = ["dillus", "g1", "g2"], Range = 1500,
    };

    private static Dictionary<string, (bool, double)> Near(params (string Id, bool Available, double Distance)[] members)
    {
        var near = new Dictionary<string, (bool, double)>();
        foreach (var m in members)
            near[m.Id] = (m.Available, m.Distance);
        return near;
    }

    [Test]
    public void ACallersMembersJoin()
        => Assert.That(LinkedCamps.Joiners(Fire, "delfina", Near(("r1", true, 150), ("r2", true, 150))), Is.EqualTo(new[] { "r1", "r2" }));

    [Test]
    public void AMemberWhoIsNoCallerCallsNoOne()
        // "Pull them first, she did not aggro while I dealt with them" (2003-05-24).
        => Assert.That(LinkedCamps.Joiners(Fire, "r1", Near(("delfina", true, 150), ("r2", true, 300))), Is.Empty);

    [Test]
    public void WithoutCallersEveryMemberCallsTheOthers()
    {
        Assert.Multiple(() =>
        {
            Assert.That(LinkedCamps.Joiners(Tower, "g1", Near(("dillus", true, 364), ("g2", true, 400))), Is.EqualTo(new[] { "dillus", "g2" }));
            Assert.That(LinkedCamps.Joiners(Tower, "dillus", Near(("g1", true, 364), ("g2", true, 515))), Is.EqualTo(new[] { "g1", "g2" }));
        });
    }

    [Test]
    public void MembersOutOfRangeBusyDeadOrGoneStay()
        => Assert.That(LinkedCamps.Joiners(Tower, "dillus", Near(("g1", true, 1501), ("g2", false, 100))), Is.Empty);

    [Test]
    public void AnNpcOfNoGroupCallsNoOne()
        => Assert.That(LinkedCamps.Joiners(Tower, "someone", Near(("g1", true, 100))), Is.Empty);
}
