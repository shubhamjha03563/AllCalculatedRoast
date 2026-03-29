"""
roast_engine.py — Position-aware stat roasts with personalised lines per player.

Roast triggers:
    All positions  — pass accuracy < 70%
    Attackers      — shot conversion < 50% (min 3 shots)
    Midfielders    — tackle success < 50% (min 5 attempts) OR interceptions < 2
    Defenders      — tackle success < 50% (min 5 attempts) OR interceptions < 2

Public interface:
    get_roast_victims(players)             -> list[dict]   each dict has 'roast_type'
    build_roast_embeds(victims, match)     -> list[discord.Embed]
"""

from __future__ import annotations
import random, logging
from typing import Any
import discord

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Thresholds
# ─────────────────────────────────────────────────────────────────────────────
PASS_THRESHOLD       = 70   # % — all positions
CONVERSION_THRESHOLD = 40   # % — anyone with 3+ shots
TACKLE_THRESHOLD     = 25   # % — mids/defenders, min 5 attempts
INT_THRESHOLD        = 1    # count — mids/defenders
LOW_PASS_MAX_ATT     = 7    # attempted passes — below this triggers caution
LOW_PASS_MAX_PCT     = 90   # accuracy threshold for low pass caution

# ─────────────────────────────────────────────────────────────────────────────
# Position bucketing
# ─────────────────────────────────────────────────────────────────────────────
_ATTACKER_KEYWORDS  = {"attacking", "finisher", "forward", "striker", "winger", "second striker"}
_MIDFIELDER_KEYWORDS = {"midfield", "creator", "magician", "recycler", "playmaker", "box to box", "defensive mid", "cdm", "cam", "cm"}
_DEFENDER_KEYWORDS  = {"defend", "defensive boss", "sweeper", "centre back", "fullback", "wing back", "keeper", "goalkeeper"}

def _position_bucket(position: str) -> str:
    """Returns 'attacker', 'midfielder', 'defender', or 'unknown'."""
    p = position.lower()
    if any(k in p for k in _ATTACKER_KEYWORDS):
        return "attacker"
    if any(k in p for k in _MIDFIELDER_KEYWORDS):
        return "midfielder"
    if any(k in p for k in _DEFENDER_KEYWORDS):
        return "defender"
    return "unknown"

# ─────────────────────────────────────────────────────────────────────────────
# Player registry
# ─────────────────────────────────────────────────────────────────────────────
PLAYER_REGISTRY: dict[str, dict] = {
    "RoyalBannaJi": {
        "discord_id": "932904102659260466",
        "club": "Arsenal",
        "roasts": {
            "passing": [
                "{pct}% passing. The ball was begging to be passed and you ignored it every time.",
                "Bro found teammates at {pct}% accuracy. The other {remaining}% just evaporated.",
                "{pct}%. At some point the passes stopped being mistakes and started being personal.",
                "The opposition didn't press you — they just waited for you to give it to them. {pct}%.",
                "Even on {pct}% passing nights, he still thinks he's the best player on the pitch. Respect the confidence at least.",
                "You had the ball, you had options, you had {pct}% passing. You chose chaos.",
                "Defenders win the ball. Midfielders keep the ball. You? You return the ball. {pct}%.",
                "The {pct}% passing display was almost artistic. Consistently, reliably wrong.",
                "Arsenal have gone 20 years without a title. At {pct}% passing you're carrying on the tradition of disappointment.",
                "Mikel Arteta would drop you for this. {pct}% passing and Arsenal still hasn't won the league.",
                "{pct}% passing. Even the Arsenal trophy cabinet is embarrassed, and that's saying something.",
                "The Gunners choke every title race. You're choking every pass. Hereditary. {pct}%.",
            ],
            "conversion": [
                "{shots} shots. The goalkeeper went home feeling like a champion. {pct}% conversion.",
                "Took {shots} shots. Scored {goals}. The goal somehow felt like an accident at {pct}%.",
                "The definition of a threat: someone the goalkeeper is mildly concerned about. {shots} shots, {pct}%.",
                "{pct}% conversion. The crossbar has been more involved in goals tonight than you.",
                "{shots} attempts. {goals} goals. The xG model is filing a complaint.",
                "Shot {shots} times at {pct}% conversion. The net has better things to do on a Wednesday night.",
                "If the posts are your best friends, tonight was a reunion. {shots} shots, {pct}%.",
                "{goals} from {shots}. The goalkeeper didn't even need to dive for most of them.",
                "Spent more time retrieving the ball from behind the goal than putting it in. {pct}%.",
                "{pct}% conversion from {shots} shots. The ball was traumatised.",
                "Arsenal strikers have been missing big chances since 2004. You're keeping the tradition alive. {pct}% conversion.",
                "{pct}% conversion. The Arsenal curse extends to Pro Clubs apparently.",
                "Missed {shots} shots at {pct}%. Olivier Giroud would've scored those. That's the worst thing I can say.",
                "Arsenal fans watch their team bottle it every season. Now they watch you bottle it too. {pct}%.",
            ],
            "low_passes": [
                "{pass_att} passes. The team played a 10v11 because you decided to go solo tonight.",
                "Touched the ball {pass_att} times and passed it less. The rest was a personal project.",
                "{pass_att} passes distributed. The other 10 players are wondering where their touches went.",
                "You had the ball. Nobody else did. {pass_att} passes. That's not football, that's hoarding.",
                "{pass_att} passes. The coach drew up a system. You drew up your own system.",
            ],
        },
    },
    "PJ10 x": {
        "discord_id": "877198629092339712",
        "roasts": {
            "passing": [
                "{pct}% passing. The opposition's midfielder sends his regards and a fruit basket.",
                "Every pass at {pct}% accuracy was a little gift. The opposition loved every one.",
                "{pct}%. You were essentially playing for both teams tonight.",
                "Touched it, moved it, lost it. Repeat. {pct}% pass accuracy.",
                "The possession stats looked great until you look at who was in possession. {pct}%.",
                "You gave the ball away so consistently at {pct}% that the opposition started expecting it.",
                "{pct}% passing. The ball had a better night with the other team.",
                "Asked for the ball, got the ball, gave the ball back to the wrong people. {pct}%.",
            ],
            "tackling": [
                "{pct}% tackle success. You went in {attempted} times like you meant it. You didn't mean it.",
                "Attempted {attempted} tackles and won {made}. The other {remaining} were generous donations.",
                "{pct}% tackle success. The opposition winger said you were his favourite defender tonight.",
                "Went in for {attempted} tackles. Won {made}. The maths are embarrassing.",
                "The tackles were brave. The {pct}% success rate was not. Brave is not the same as good.",
                "{attempted} attempts, {made} wins. A {pct}% rate in any other profession gets you fired.",
                "You chased the ball for {attempted} tackles and got rewarded with {made}. Hustle without result.",
                "{pct}% tackle success. The ground spent more time with the ball than you did.",
            ],
            "interceptions": [
                "{count} interceptions. The opposition passed through you like you were a revolving door.",
                "Covered every blade of grass and intercepted {count} passes. The grass saw more action.",
                "{count} interceptions. You were a midfielder in body only tonight.",
                "The ball moved around you, past you, through you. {count} interceptions.",
                "{count}. You read the game like a book written in a language you don't speak.",
                "Intercepted {count} passes. The opposition finished the game having never met you.",
                "{count} interceptions from the engine room. The engine was in neutral all night.",
                "Stood between the defence and attack and intercepted {count} passes. Decorative.",
            ],
            "conversion": [
                "{shots} shots, {pct}% conversion. The goalkeeper barely broke a sweat.",
                "When you shoot it's an event. {shots} shots, {pct}%. Underwhelming events.",
                "{pct}% from {shots} shots. The ball had somewhere better to be. Apparently not the net.",
                "Tried {shots} times. Scored {goals}. The net is still waiting.",
                "{shots} shots. The posts, the keeper, row Z — everyone got a touch except the goal. {pct}%.",
            ],
            "low_passes": [
                "Only {pass_att} passes. The team was available. You just weren't interested.",
                "{pass_att} passes and yet somehow still took up space in midfield. Mysterious.",
                "Played {pass_att} passes. The rest of the team played without you.",
                "The midfield had one job: connect the team. {pass_att} passes. Partial credit.",
                "{pass_att} passes is a training ground stat. This is a real game.",
            ],
        },
    },
    "ShreyChoudhary98": {
        "discord_id": "391344367433940997",
        "club": "Manchester United",
        "roasts": {
            "passing": [
                "{pct}% passing. The link was missing. It was you.",
                "You're supposed to be the connector. {pct}% passing — more of a disconnector tonight.",
                "{pct}%. You bridged the gap between your team and the opposition's possession stats.",
                "The ball came to you and the opposition came alive. {pct}% passing.",
                "{pct}% passing. The opposition's press was helped enormously by your contribution.",
                "Found the opposition more often than your teammates tonight. {pct}%.",
                "{pct}% — you were technically playing but the passes disagreed with the assignment.",
                "Played as a link man at {pct}% accuracy. The chain had a very weak link.",
                "Manchester United paid £80m for players who do less damage than your {pct}% passing tonight.",
                "{pct}% passing. Ten Hag got sacked for less. Erik Ten Hag got sacked for exactly this.",
                "Man United's midfield has been a disaster for a decade. You fit right in at {pct}%.",
                "The Theatre of Dreams is now the Theatre of {pct}% passing. You've brought it to Pro Clubs.",
            ],
            "conversion": [
                "{shots} shots, {pct}% conversion. The posts have filed a noise complaint.",
                "Shot {shots} times. The goalkeeper needed {goals} saves. That's telling. {pct}%.",
                "{pct}% conversion. You made shooting look exhausting and unrewarding.",
                "{goals} from {shots}. The ball needed more convincing than the net was prepared to offer.",
                "Tried from distance, tried from close, tried from everywhere. {shots} shots. {pct}%. Tried.",
                "{shots} attempts. {pct}% conversion. The scoresheet is ruthless.",
                "{pct}% from {shots} shots. The goal was open on several occasions and politely declined.",
                "Lined up {shots} shots at {pct}% conversion. Precision was not tonight's theme.",
                "Man United spent £1 billion on strikers who miss like this. You're doing it for free. {pct}%.",
                "{pct}% conversion. Rasmus Hojlund would feel better reading this.",
                "United fans have been crying since Fergie left. Now they're crying about your {pct}% conversion.",
                "{shots} shots, {goals} goals, {pct}%. The Stretford End has seen this before. Too many times.",
            ],
            "low_passes": [
                "{pass_att} passes from the player whose whole job is to link things. Things were not linked.",
                "Linking midfield and attack requires more than {pass_att} passes. Just saying.",
                "{pass_att} passes. You were on the pitch, technically.",
                "The connection between midfield and attack was {pass_att} passes strong. Snapped.",
                "{pass_att} passes. The team was waiting. The pass never came.",
            ],
        },
    },
    "itspaynewhackhim": {
        "discord_id": "255663738068271104",
        "club": "Liverpool",
        "roasts": {
            "passing": [
                "{pct}% passing. The danger was self-inflicted.",
                "Gave the ball away at {pct}% accuracy. The press didn't need to press — you did their job.",
                "{pct}%. You were your own worst enemy tonight and the opposition's best friend.",
                "The pass completion rate was {pct}%. The opposition's press completion rate was much higher.",
                "Tried to play it simple at {pct}% passing. Simple was not achieved.",
                "{pct}% passing. The goalkeeper started the move more than once. From your passes.",
                "Controlled, composed, and then {pct}% passing. The last part ruins the sentence.",
                "{pct}% — you found passes that technically existed but shouldn't have been attempted.",
                "Liverpool play Tiki-Taka under Slot. You play give-it-away at {pct}%. Not the same thing.",
                "{pct}% passing. Xabi Alonso never did this. Neither did Gerrard. You're a new kind of Liverpool.",
                "You'll never walk alone — but your passes will. {pct}% accuracy tonight.",
                "{pct}% passing from a Liverpool fan. Klopp left because of you. I'm almost certain.",
            ],
            "tackling": [
                "Went in {attempted} times and won {made}. The full-back you were supposed to stop is having his best game.",
                "{pct}% tackle success. You committed to {attempted} tackles with the conviction of someone who'd never tried before.",
                "The ball won {remaining} of the {attempted} duels. The ball is not supposed to win duels.",
                "{attempted} tackle attempts. {made} wins. {pct}%. The academy would like a word.",
                "Sliding into tackles and sliding out empty-handed. {attempted} attempts. {pct}%.",
                "You tried {attempted} times to win the ball. It said no {remaining} times. {pct}%.",
                "{pct}% tackle success. The grass has a better win rate against opponents tonight.",
                "Committed {attempted} tackles at {pct}% success. Commitment without ability is just enthusiasm.",
                "Liverpool's press is legendary. Your {pct}% tackle success is the opposite of legendary.",
                "{pct}% tackle success. Virgil Van Dijk is somewhere questioning his life choices.",
                "The Liverpool way involves winning the ball. {pct}% tackle success is not the Liverpool way.",
                "{made} from {attempted} tackles. Fabinho in his prime never had a night this bad. {pct}%.",
            ],
            "interceptions": [
                "{count} interceptions. The gaps you were supposed to fill filled themselves with opposition players.",
                "Screened the defence at {count} interceptions. The screen had cracks.",
                "{count}. You were in position. The ball just didn't want to be intercepted by you.",
                "Read {count} passes correctly. The opposition wrote the book you were supposed to read.",
                "{count} interceptions. You were present. The defending was absent.",
                "The opposition played through the middle {count} times too many. You watched.",
                "{count} interceptions. The line between midfielder and spectator was thin tonight.",
                "Stood in the right place {count} times and let the ball through every time.",
                "{count} interceptions. Henderson intercepted more in his sleep.",
                "Liverpool built their identity on pressing and winning the ball. {count} interceptions tonight. Identity crisis.",
                "{count} interceptions from a Liverpool fan. The Anfield crowd would've booed you off.",
                "The midfield engine of Liverpool. {count} interceptions. The engine has stalled.",
            ],
            "conversion": [
                "{shots} shots, {pct}% conversion. The venture forward did not pay off.",
                "Took {shots} shots. Scored {goals}. The goal was a surprise to everyone including you.",
                "{pct}% conversion — the forward run ended with the ball going anywhere but in.",
                "{shots} attempts, {pct}%. The goalkeeper was mildly inconvenienced.",
                "{goals} from {shots} shots. The goal threat was theoretical. {pct}%.",
            ],
            "low_passes": [
                "{pass_att} passes. The team was open. The passes were not.",
                "Distributed the ball {pass_att} times. The team was waiting for more.",
                "{pass_att} passes from the deepest midfielder. The building blocks weren't laid.",
                "Played {pass_att} passes. The rest of the squad are wondering where their ball is.",
                "{pass_att} passes. The team played around you rather than through you.",
            ],
        },
    },
    "cosmicfps06": {
        "discord_id": "334404960747782167",
        "club": "Real Madrid",
        "roasts": {
            "passing": [
                "{pct}% passing. The step-overs were great. The passes were not.",
                "Beat three men with a brilliant run, then passed it to the fourth. {pct}%.",
                "{pct}% — the creativity was there. The accuracy had the night off.",
                "Dribbled brilliantly and passed badly. {pct}%. The last step kept being wrong.",
                "The ball moved beautifully until it needed to reach a teammate. {pct}%.",
                "{pct}% passing accuracy. The flair was unquestionable. The fundamentals were.",
                "Created several moments of brilliance that ended with {pct}% passing.",
                "The dribbles said yes. The passes said {pct}%.",
                "Real Madrid win everything with class. {pct}% passing is not class. It is not even close.",
                "{pct}% passing. Modric never had a night this bad. Not once in 15 years.",
                "The Bernabeu demands excellence. {pct}% passing would get you booed off in the first half.",
                "Hala Madrid. {pct}% passing. The 'Hala' is very much not applicable tonight.",
            ],
            "conversion": [
                "{shots} shots. The goalkeeper had a highlight reel of saves to make. Some were embarrassing. {pct}%.",
                "Got into every position imaginable and scored {goals} from {shots} shots. The positions were better than the shots.",
                "{pct}% conversion — the skill got you there and then abandoned you at the finish.",
                "Beat defenders to get to {shots} shots and then lost to the goalkeeper at {pct}%.",
                "{goals} goals from {shots} shots. The tricks got you in, the finishing got you out. {pct}%.",
                "{shots} attempts at {pct}% conversion. The rainbow flick beforehand deserved better.",
                "The setup was immaculate. The finish was {pct}%. Classic.",
                "{pct}% — all the build-up and the ending was disappointing. Like a film with a bad third act.",
                "Real Madrid have Mbappe, Vinicius, Bellingham. You had {shots} shots and {pct}% conversion. The gap is massive.",
                "{pct}% conversion. Benzema scored 44 goals in a season. You scored {goals} from {shots} shots.",
                "Los Blancos expect goals. {shots} shots, {pct}% conversion. Los Blancos are disappointed.",
                "Real Madrid always find a winner. You found {pct}% conversion. Not the same.",
            ],
            "low_passes": [
                "{pass_att} passes. You kept it, beat the man, beat another man, lost it. Repeat.",
                "The dribbling stats were great. The {pass_att} passes stat shows the other side.",
                "{pass_att} passes. Some of those solo runs needed an exit pass. They didn't get one.",
                "Amazing with the ball. {pass_att} passes means the team didn't see much of it.",
                "{pass_att} passes. The ball was in good hands. Just your hands. Only yours.",
            ],
        },
    },
    "metalstone_11": {
        "discord_id": "353420754534137859",
        "roasts": {
            "passing": [
                "{pct}% passing. The mistakes are part of the process. There were a lot of mistakes. {pct}%.",
                "Young, learning, {pct}% passing. The curriculum includes not giving it away.",
                "{pct}% — the effort was visible. The accuracy less so.",
                "Passes at {pct}% accuracy. The development curve has a few more bends in it.",
                "Tried to play the killer pass. Found the opposition at {pct}%. The killer was the pass.",
                "{pct}% passing. Every player goes through this phase. Most get through it faster.",
                "The intent was good. The execution at {pct}% needs work. That's a kind way of saying it.",
                "{pct}% — you were trying things. The things didn't work. But you were trying.",
            ],
            "conversion": [
                "{shots} shots. {goals} goals. {pct}% conversion. The finishing will come. It didn't come tonight.",
                "Got into great positions {shots} times. The finishing wasn't there at {pct}%.",
                "{pct}% conversion. The hunger was there. The end product needs more cooking.",
                "Worked hard to get {shots} shots and {pct}% conversion. The work rate deserved better finishing.",
                "{goals} from {shots}. The positions were right. The finish was still developing. {pct}%.",
                "Shot {shots} times and converted {pct}%. The development journey continues.",
                "{pct}% — you'll look back at these games and understand what went wrong. Tonight, it's just painful.",
                "{shots} attempts. The net has been patient waiting for metalstone_11 to find it properly.",
            ],
            "tackling": [
                "Went in {attempted} times at {pct}% success. Young and fearless. Just needs to be right more often.",
                "{attempted} tackles, {made} won. {pct}%. The engine is there. The timing needs calibrating.",
                "{pct}% tackle success from {attempted} attempts. Brave. Inaccurate. But brave.",
                "Won {made} from {attempted} tackles. {pct}%. The lesson is about when to go, not just going.",
                "{attempted} attempts at {pct}% success. Enthusiastic defending. Effective defending is different.",
            ],
            "low_passes": [
                "{pass_att} passes. Getting on the ball more is part of growing into the role.",
                "Only {pass_att} passes. The team needs you more involved. Don't be afraid of it.",
                "{pass_att} passes — you're still finding your feet. But you need to demand the ball more.",
                "{pass_att} passes. Every great player has games where they disappear. Don't make it a habit.",
                "The contribution was {pass_att} passes. The team needed more. Come on.",
            ],
        },
    },
    "Chitraksh08": {
        "discord_id": "741616918015770706",
        "club": "Manchester United",
        "roasts": {
            "passing": [
                "{pct}% passing. The distribution was meant to set the team up. It set the opposition up instead.",
                "Received the ball in space and found the opposition at {pct}% accuracy. Generous.",
                "{pct}% — the ball went to some interesting places tonight. None of them were your teammates.",
                "Composed, calm, {pct}% passing. The composure was a lie.",
                "The deepest midfielder gave the ball away at {pct}%. The defence said a prayer.",
                "{pct}% passing from the base of midfield. The base cracked.",
                "Tried to play through the press at {pct}% passing. The press won.",
                "{pct}% — you were involved in plenty of attacks. Unfortunately several were the opposition's.",
                "Man United's midfield has been broken for years. You're doing your part to keep the tradition going. {pct}%.",
                "{pct}% passing. Bruno Fernandes would've hit someone in the face by now out of frustration.",
                "The Theatre of Dreams needs better passing than {pct}%. Sir Alex is looking down shaking his head.",
                "{pct}% passing. Old Trafford has witnessed some dark moments. This is now one of them.",
            ],
            "tackling": [
                "Went in {attempted} times and won {made}. The other {remaining} were just sliding presentations.",
                "{pct}% tackle success. The ball spent more time leaving your challenges than entering them.",
                "{attempted} tackles at {pct}% success. The intent was defensive. The effect was not.",
                "Won {made} from {attempted} tackles. {pct}%. The ground got to the ball before you most times.",
                "Challenged {attempted} times. The {remaining} losses hurt the team. {pct}%.",
                "{pct}% tackle success. The tackle stat says CDM. The success rate says otherwise.",
                "Put in {attempted} tackles and got {made}. A {pct}% win rate in a fight would concern anyone.",
                "{attempted} attempts, {pct}% success. At least you tried. That's the nicest thing to say.",
                "{pct}% tackle success. Roy Keane would've taken out three players by now just watching this.",
                "Man United's midfield hasn't been physical since Keane left. {pct}% tackle success continues the drought.",
                "{made} from {attempted} tackles. United fans want fighters. {pct}% is not fighting.",
                "{pct}% tackle success. The United faithful have seen enough. So have we.",
            ],
            "interceptions": [
                "{count} interceptions. The middle of the park was open for business and you weren't the bouncer.",
                "Supposed to screen the defence. The screen had a {count}-interception-sized hole in it.",
                "{count} interceptions. The opposition's number 8 didn't even see you tonight.",
                "Covered the ground. Covered {count} passes. The ground was covered. The passes weren't.",
                "{count} interceptions from the midfield anchor. The anchor was decorative.",
                "The defensive midfielder intercepted {count} passes. The role description mentions more than that.",
                "{count}. You were there. The interceptions weren't. A ghost with a jersey.",
                "Read {count} passes correctly. The opposition wrote more than {count} passes tonight.",
                "{count} interceptions. Even Man United's current midfield intercepts more than this. That's your bar.",
                "Nemanja Matic played into his 30s because no one at United could replace him. {count} interceptions explains why.",
                "{count} interceptions. The gap between Roy Keane and this performance cannot be measured.",
                "United's midfield has been a revolving door for a decade. {count} interceptions keeps it spinning.",
            ],
            "conversion": [
                "{shots} shots, {pct}% conversion. The forward excursion was brave and unproductive.",
                "Left the defensive post to shoot {shots} times at {pct}%. The defence missed you.",
                "{pct}% conversion from {shots} shots. The penalty taker reputation took a hit tonight.",
                "{goals} goals from {shots} shots. {pct}%. A CDM who can shoot — can.",
                "{shots} shots and {pct}% conversion. The goal-scoring ability is a work in progress.",
            ],
            "low_passes": [
                "{pass_att} passes from the player in the middle of everything. Nothing went through you.",
                "The team tried to play through the base of midfield. The base had {pass_att} passes.",
                "{pass_att} passes. The engine room took a night off.",
                "Distributed {pass_att} times. The midfield was undernourished.",
                "{pass_att} passes. The deepest midfielder should touch it most. You touched it least.",
            ],
        },
    },
    "jashnasalvi": {
        "discord_id": "435878710919299084",
        "roasts": {
            "passing": [
                "{pct}% passing. The attack was oriented — just in the wrong direction.",
                "Gave it away at {pct}% accuracy. The opposition appreciated the service.",
                "{pct}% — every misplaced pass was someone else's chance. They took them.",
                "Found the opposition more than your own team tonight. {pct}%.",
                "{pct}% passing. The movement was sharp. The passing was blunt.",
                "Pressed high, moved well, passed badly. {pct}%. Three out of four.",
                "{pct}% accuracy. You played well in a chaotic, opponent-benefiting kind of way.",
                "The ball went to some creative places tonight. None of them were the right places. {pct}%.",
            ],
            "conversion": [
                "{shots} shots. Scored {goals}. The goal was the least convincing part of the night. {pct}%.",
                "{pct}% conversion — you lined up the shots and the shots lined up the opposition keeper.",
                "Got into positions {shots} times. The positions were better than the decisions. {pct}%.",
                "{goals} from {shots}. The attack was relentless. The finishing was not. {pct}%.",
                "{shots} attempts, {pct}% conversion. The goal will come. It just didn't come tonight.",
                "Shot from everywhere. Scored {goals}. {pct}%. The goalkeeper barely had to think.",
                "{pct}% from {shots} shots. The strikers' union has questions.",
                "{shots} shots and {pct}% conversion. Quantity was there. Quality was shy.",
            ],
            "low_passes": [
                "{pass_att} passes. The attack was one-dimensional because you kept it that way.",
                "Pressed and ran and attacked and passed {pass_att} times. The passing was the missing piece.",
                "{pass_att} passes. You played like the ball was a hot potato.",
                "Combined with teammates {pass_att} times. That's not a combination, that's an accident.",
                "{pass_att} passes. The team needs you to involve others. Every. Single. Time.",
            ],
        },
    },
    "ChachaToji": {
        "discord_id": "911476759973744700",
        "club": "Real Madrid",
        "roasts": {
            "passing": [
                "{pct}% passing. The versatility was on display. The accuracy wasn't.",
                "Plays every position and passes at {pct}%. Some positions are worse than others.",
                "{pct}% — the overcooked pass is a ChachaToji signature move, apparently.",
                "Tried to thread it, tried to play it simple, tried to play it long. {pct}%. All wrong.",
                "The vision was there. The execution at {pct}% was somewhere else entirely.",
                "{pct}% passing. Versatile player, versatile mistakes.",
                "Jack of all trades, {pct}% at the most basic one. Passing.",
                "Comfortable in every position except the one where you give the ball to your own team. {pct}%.",
                "Real Madrid win La Liga with 95% pass accuracy. You're contributing {pct}%. The Bernabeu is not impressed.",
                "{pct}% passing. Luka Modric could pass in his sleep at 90%. You are awake and managing {pct}%.",
                "Real Madrid's DNA is possession, precision, patience. {pct}% passing has none of those things.",
                "{pct}% passing from a Real Madrid fan. Florentino Perez would've sold you in January.",
            ],
            "tackling": [
                "{pct}% tackle success. The tackles were committed. So were the errors.",
                "Went in {attempted} times with everything and won {made}. Everything wasn't enough. {pct}%.",
                "{attempted} tackles, {pct}% success. The ball dodged you every single time.",
                "{made} from {attempted}. {pct}%. The tackle was overcooked. Most of them were.",
                "Won {made} duels from {attempted} attempts. {pct}% — versatile at losing as well.",
                "{attempted} attempts at {pct}% success. You were a one-man revolving door for the opposition.",
                "{pct}% tackle success. Every lunge was enthusiastic. Every result was disappointing.",
                "Challenged {attempted} times and won {made}. {pct}%. The positional play was there. The execution wasn't.",
                "Casemiro won four Champions Leagues. You won {made} from {attempted} tackles at {pct}%. Different players.",
                "{pct}% tackle success. Real Madrid's defensive midfield has never looked this bad. Not once.",
                "The Bernabeu demands more than {pct}% tackle success. The Bernabeu demands Casemiro.",
                "{made} from {attempted} tackles. {pct}%. Fede Valverde would be disgusted.",
            ],
            "interceptions": [
                "{count} interceptions. You were everywhere on the pitch except where the passes were going.",
                "Covered every zone and intercepted {count} passes. The zones were wrong.",
                "{count}. The most versatile player found the one thing he couldn't do tonight: read the game.",
                "Versatile in every way except anticipating where the ball was going. {count} interceptions.",
                "{count} interceptions from a player who covers the whole pitch. The pitch coverage wasn't.",
                "Played everywhere and intercepted {count} times. The everywhere didn't include the right spots.",
                "{count} interceptions. The ball went around you, past you, and through you. {count} times caught.",
                "Read {count} passes. The opposition wrote more passes than you read.",
                "{count} interceptions. Casemiro averaged more per half. Per half.",
                "Real Madrid's midfield is Bellingham, Valverde, Modric. Your {count} interceptions suggests you are not those.",
                "{count} interceptions. The Champions League anthem played in your head and nothing happened.",
                "Hala Madrid. {count} interceptions. The Madrid way is to read the game. {count} times you didn't.",
            ],
            "conversion": [
                "{shots} shots, {pct}% conversion. The versatility doesn't extend to finishing.",
                "Overcooked {shots} shots at {pct}% conversion. The finishing was also overcooked.",
                "{pct}% — you found creative ways to miss. One of them involved the corner flag.",
                "Got into positions {shots} times and converted {pct}%. The positions were better than the player.",
                "{goals} from {shots} shots. {pct}%. The goal was almost as accidental as the misses.",
            ],
            "low_passes": [
                "{pass_att} passes. The versatility apparently includes minimalism.",
                "Touched the ball {pass_att} times in a passing sense. The rest was personal.",
                "{pass_att} passes from the player who can do everything. Passing is something.",
                "Played {pass_att} passes. ChachaToji usually brings more than that.",
                "{pass_att} passes. The most versatile player on the pitch was the least available one.",
            ],
        },
    },
    "vishwask12": {
        "discord_id": "",
        "roasts": {
            "passing": [
                "{pct}% passing. The spark went the wrong direction.",
                "Lit up the midfield at {pct}% passing accuracy. The opposition was illuminated.",
                "{pct}% — you sparked things up for everyone. Including the other team.",
                "The midfield came alive at {pct}% passing. The wrong midfield.",
                "Played with intensity and {pct}% passing. The intensity was misplaced.",
                "{pct}% accuracy. You sparked, you moved, you gave it away. Rinse repeat.",
                "Dynamic, energetic, {pct}% passing. Two out of three is not good enough.",
                "{pct}% passing tonight. The electricity had a wiring problem.",
            ],
            "tackling": [
                "{attempted} tackles at {pct}% success. Fast into challenges. Slow to win them.",
                "{pct}% tackle success. Went in hard {attempted} times and got the ball {made} times.",
                "High energy, {pct}% tackle success. The energy isn't the problem.",
                "{made} from {attempted}. {pct}%. The effort was there. The accuracy wasn't.",
                "{attempted} attempts and {made} wins. {pct}% — enthusiastic defending is still bad defending.",
            ],
            "interceptions": [
                "{count} interceptions. Moved fast and intercepted nothing. Physics is against you.",
                "Pressed and chased and tracked and intercepted {count} times. The tracking was off.",
                "{count} interceptions. The Spark was everywhere except where the passes were going.",
                "Read the game at {count} interceptions. The book was in a different language tonight.",
                "{count} interceptions despite covering enormous ground. The ground wasn't the problem.",
            ],
            "conversion": [
                "{shots} shots, {pct}% conversion. Got there quickly and finished slowly.",
                "{pct}% from {shots} shots. The runs were sharp. The finishing was not.",
                "{goals} from {shots} shots. The Spark got to the ball. What happened next was less impressive.",
                "{shots} attempts at {pct}% conversion. The pace got you in, the touch let you down.",
                "{pct}% — electric movement, dim finishing. {shots} shots to prove it.",
            ],
            "low_passes": [
                "{pass_att} passes. The energy was high. The sharing was low.",
                "Covered the ground and passed {pass_att} times. The ground got more touches.",
                "{pass_att} passes. More running than passing. The team needs the passing.",
                "{pass_att} passes distributed. You kept finding the ball and then keeping it.",
                "High press, low pass output. {pass_att} passes. The balance is off.",
            ],
        },
    },
}

_UNKNOWN_ROASTS = {
    "vishwak12": {
        "discord_id": "",
        "roasts": {
            "passing": [
                "{pct}% passing. The spark went the wrong direction.",
                "Lit up the midfield at {pct}% passing accuracy. The opposition was illuminated.",
                "{pct}% — you sparked things up for everyone. Including the other team.",
                "The midfield came alive at {pct}% passing. The wrong midfield.",
                "Played with intensity and {pct}% passing. The intensity was misplaced.",
                "{pct}% accuracy. You sparked, you moved, you gave it away. Rinse repeat.",
                "Dynamic, energetic, {pct}% passing. Two out of three is not good enough.",
                "{pct}% passing tonight. The electricity had a wiring problem.",
            ],
            "tackling": [
                "{attempted} tackles at {pct}% success. Fast into challenges. Slow to win them.",
                "{pct}% tackle success. Went in hard {attempted} times and got the ball {made} times.",
                "High energy, {pct}% tackle success. The energy isn't the problem.",
                "{made} from {attempted}. {pct}%. The effort was there. The accuracy wasn't.",
                "{attempted} attempts and {made} wins. {pct}% — enthusiastic defending is still bad defending.",
            ],
            "interceptions": [
                "{count} interceptions. Moved fast and intercepted nothing. Physics is against you.",
                "Pressed and chased and tracked and intercepted {count} times. The tracking was off.",
                "{count} interceptions. The Spark was everywhere except where the passes were going.",
                "Read the game at {count} interceptions. The book was in a different language tonight.",
                "{count} interceptions despite covering enormous ground. The ground wasn't the problem.",
            ],
            "conversion": [
                "{shots} shots, {pct}% conversion. Got there quickly and finished slowly.",
                "{pct}% from {shots} shots. The runs were sharp. The finishing was not.",
                "{goals} from {shots} shots. The Spark got to the ball. What happened next was less impressive.",
                "{shots} attempts at {pct}% conversion. The pace got you in, the touch let you down.",
                "{pct}% — electric movement, dim finishing. {shots} shots to prove it.",
            ],
            "low_passes": [
                "{pass_att} passes. The energy was high. The sharing was low.",
                "Covered the ground and passed {pass_att} times. The ground got more touches.",
                "{pass_att} passes. More running than passing. The team needs the passing.",
                "{pass_att} passes distributed. You kept finding the ball and then keeping it.",
                "High press, low pass output. {pass_att} passes. The balance is off.",
            ],
        },
    },
}

_UNKNOWN_ROASTS = {
    "passing": [
        "{name} found teammates at {pct}% accuracy. The other {remaining}% found the opposition.",
        "{pct}% passing from {name}. I'd know who to blame if I knew who {name} was.",
        "{name} gave the ball away at {pct}%. That's why we need regulars.",
        "You play so rarely that even the passes are unfamiliar. {name}, {pct}%.",
        "{pct}% from {name}. Show up more often and maybe the passes will know where to go.",
    ],
    "conversion": [
        "{name} took {shots} shots and scored {goals}. {pct}% conversion. That's why you should play regularly.",
        "{pct}% conversion from {name}. Match sharpness is earned, not gifted. Show up to earn it.",
        "{shots} shots. {goals} goals. {pct}%. {name} was a threat to everyone, including their own xG.",
        "I don't have {name} in my notes because they barely play. {pct}% conversion proves the point.",
        "{shots} attempts, {pct}% conversion. {name} needs more games before the finishing comes.",
    ],
    "tackling": [
        "{name} won {made} of {attempted} tackles at {pct}%. I'd tell them what they did wrong but they won't be back for months.",
        "{pct}% tackle success from {name}. Irregular player, irregular defending.",
        "{name} attempted {attempted} tackles and won {made}. The match fitness wasn't there. {pct}%.",
        "{made} from {attempted} tackles. {name} at {pct}% — the legs said no before the brain did.",
        "I don't even have {name}'s Discord because they barely show up. {pct}% tackle success confirms the attendance issue.",
    ],
    "interceptions": [
        "{name} intercepted {count} passes. The game passed through them like they weren't there.",
        "{count} interceptions from {name}. You play so rarely the opposition doesn't even notice you.",
        "{name}. {count} interceptions. Ghost in the machine. Ghost on the pitch.",
        "I'd roast {name} properly if they played regularly enough for me to have material. {count} interceptions.",
        "{count} from {name}. The anonymity is consistent with the appearance record.",
    ],
    "low_passes": [
        "{name} attempted {pass_att} passes. Come on. I don't even have your Discord. Be brave and pass the ball.",
        "{pass_att} passes from {name}. You play so rarely you're still learning the system.",
        "I can't tag {name} because they're a ghost. {pass_att} passes. On brand for a ghost.",
        "{pass_att} passes. {name} was on the pitch. The contribution was not.",
        "{name}. {pass_att} passes. Still finding their feet. Still not finding their teammates.",
    ],
}




# ─────────────────────────────────────────────────────────────────────────────
# Combo roasts — triggered by extreme stat combos, override normal pool
# ─────────────────────────────────────────────────────────────────────────────

_COMBO_ROASTS = {
    "finishing_collapse": [
        "{shots} shots. {goals} goals.\n\nThe goalkeeper is naming his first child after you.",
        "{shots} attempts at {pct}% conversion.\n\nYou didn't miss — you curated a save compilation.",
        "{shots} shots.\n\nThe net filed a missing person report.",
        "{shots} shots, {pct}% conversion.\n\nThe crossbar sent a thank you card.",
        "{goals} goals from {shots} shots.\n\nThe opposition keeper is on a bonus tonight. You provided it.",
    ],
    "ghost": [
        "Full match played.\n\nStill awaiting first confirmed contribution.",
        "You were on the pitch. Allegedly.",
        "Invisible performance. Even the ball avoided you.",
        "Technically present. Practically absent.",
        "The shirt was there. The player inside it was not.",
    ],
    "selfish": [
        "{shots} shots. 0 assists.\n\nTeammates were optional tonight.",
        "Shot {shots} times and passed responsibility every single time.",
        "Hero ball attempted. Team play declined. {shots} shots, {goals} goals.",
        "{shots} attempts with 0 assists. The team played a supporting role in your personal highlight reel.",
        "Every touch became a shot. The concept of the pass was briefly forgotten. {shots} shots.",
    ],
}

# Extra lines added to end of roast occasionally
_EXTRA_LINES = [
    "The panel is concerned.",
    "We move on.",
    "Questions will be asked.",
    "This will be reviewed internally.",
    "The coaching staff have been informed.",
    "Training has been booked.",
    "No further questions.",
]

# Special event intros — rare, prepended to roast
_SPECIAL_EVENTS = [
    "📺 VAR Review\n\nAfter checking the replay...\nYes, it was worse than it looked.\n\n",
    "🎙️ Breaking news from the studio:\n\n",
    "📋 Official match report notation:\n\n",
    "⚠️ The following has been flagged for review:\n\n",
]


def _get_tier(rtype: str, pct: int) -> str:
    """Return severity tier based on roast type and stat value."""
    if rtype == "conversion":
        if pct < 20: return "nuclear"
        if pct < 35: return "heavy"
        return "mild"
    if rtype == "passing":
        if pct < 50: return "nuclear"
        if pct < 62: return "heavy"
        return "mild"
    if rtype == "tackling":
        if pct < 15: return "nuclear"
        if pct < 30: return "heavy"
        return "mild"
    return "mild"


# ─────────────────────────────────────────────────────────────────────────────
# Public interface
# ─────────────────────────────────────────────────────────────────────────────

def get_roast_victims(players: list[dict]) -> list[dict]:
    """Check each player's stats against position-aware thresholds."""
    victims = []
    seen = set()   # one roast per player per match

    for p in players:
        name     = p.get("name", "")
        position = p.get("position", "")
        bucket   = _position_bucket(position)

        # ── Pass accuracy (all positions) ─────────────────────────────────
        attempted = p.get("passes_attempted", 0)
        completed = p.get("passes_completed", 0)
        if attempted >= 5:
            pass_pct = round(completed / attempted * 100)
            if pass_pct < PASS_THRESHOLD and (name, "passing") not in seen:
                victims.append({**p, "roast_type": "passing", "pass_pct": pass_pct})
                seen.add((name, "passing"))

        # ── Conversion rate — anyone with enough shots ───────────────────
        shots = p.get("shots", 0)
        goals = p.get("goals", 0)
        if shots >= 3:
            conv_pct = round(goals / shots * 100)
            if conv_pct < CONVERSION_THRESHOLD and (name, "conversion") not in seen:
                victims.append({**p, "roast_type": "conversion",
                                "conv_pct": conv_pct, "shots": shots, "goals": goals})
                seen.add((name, "conversion"))

        # ── Midfielder / Defender: tackle success ─────────────────────────
        if bucket in ("midfielder", "defender", "unknown"):
            tkl_made = p.get("tackles", 0)
            tkl_att  = p.get("tackles_attempted", 0)
            if tkl_att >= 5:
                tkl_pct = round(tkl_made / tkl_att * 100)
                if tkl_pct < TACKLE_THRESHOLD and (name, "tackling") not in seen:
                    victims.append({**p, "roast_type": "tackling",
                                    "tkl_pct": tkl_pct, "tkl_made": tkl_made, "tkl_att": tkl_att})
                    seen.add((name, "tackling"))

        # ── Midfielder / Defender: interceptions ──────────────────────────
        if bucket in ("midfielder", "defender"):
            ints = p.get("interceptions", 0)
            if ints < INT_THRESHOLD and (name, "interceptions") not in seen:
                victims.append({**p, "roast_type": "interceptions", "int_count": ints})
                seen.add((name, "interceptions"))

    return victims


def build_roast_embeds(victims: list[dict], match_info: dict,
                       all_players: list[dict] | None = None) -> list[discord.Embed]:
    """Build one pundit-style embed per player combining praises and roasts.

    Args:
        victims:     players flagged by get_roast_victims()
        match_info:  match metadata dict
        all_players: full player list — if provided, praise-only players get verdicts too
    """
    from collections import defaultdict

    # Group roast victims by player
    roasts_by_player: dict[str, list[dict]] = defaultdict(list)
    for v in victims:
        roasts_by_player[v["name"]].append(v)

    # Build praise candidates from full player list if provided, else from victims
    praise_source = all_players if all_players else list({v["name"]: v for v in victims}.values())
    praised_by_player: dict[str, list[dict]] = defaultdict(list)
    for p in get_praise_candidates(praise_source):
        for reason in p["praise_reasons"]:
            praised_by_player[p["name"]].append({**p, **reason})

    # All unique players across roasts and praises
    all_names = set(roasts_by_player.keys()) | set(praised_by_player.keys())

    if not all_names:
        return []

    embeds = []
    score_opp = f"{match_info.get('score','?')} vs {match_info.get('opponent','?')}"

    for name in all_names:
        # Use position from any victim/praised entry for this player
        player_position = next((v.get("position", "") for v in (roasts_by_player.get(name, []) + praised_by_player.get(name, [])) if v.get("position")), "")
        registry = _fuzzy_lookup(name, player_position)
        mention  = f"<@{registry['discord_id']}>" if registry and registry.get("discord_id") else f"**{name}**"

        lines  = [mention, ""]
        footer_parts = []

        # ── Praises first (pundit bigging them up) ────────────────────────
        praises = praised_by_player.get(name, [])
        # Check if any praised player has a low-pass caution
        caution_msg = None
        for praised_player in get_praise_candidates(all_players or []):
            if praised_player["name"] == name and praised_player.get("caution"):
                c = praised_player["caution"]
                pool = _LOW_PASS_CAUTIONS.get(name, _DEFAULT_LOW_PASS_CAUTION)
                caution_msg = random.choice(pool).format(pass_att=c["pass_att"])
                break

        if praises:
            lines.append("**The Good:**")
            for p in praises:
                rtype  = p.get("type", "")
                praise = _pick_praise(registry, name, rtype, p)
                lines.append(f"  {praise}")
            if caution_msg:
                lines.append("")
                lines.append("**A word of caution:**")
                lines.append(f"  {caution_msg}")
            lines.append("")

        # ── Roasts after (pundit turning savage) ─────────────────────────
        roasts = roasts_by_player.get(name, [])
        if roasts:
            if praises:
                lines.append("**However...**")
            for v in roasts:
                rtype = v["roast_type"]
                roast = _pick_roast(registry, name, rtype, v)
                lines.append(f"  {roast}")
                footer_parts.append(_footer_stat(rtype, v))

        desc = "\n".join(lines).strip()

        # Colour: green if only praised, red if only roasted, gold if both
        if praises and roasts:
            colour = discord.Colour.gold()
        elif praises:
            colour = discord.Colour.green()
        else:
            colour = discord.Colour.orange()

        embed = discord.Embed(
            title="📺 Pundit Verdict",
            description=desc,
            colour=colour,
        )
        embed.set_footer(text=("  |  ".join(footer_parts) + f" • {score_opp}").strip("  |  "))
        embeds.append(embed)

    return embeds


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pick_roast(registry: dict | None, name: str, rtype: str, v: dict) -> str:
    shots    = v.get("shots", 0)
    goals    = v.get("goals", 0)
    assists  = v.get("assists", 0)
    pct      = v.get("pass_pct", v.get("conv_pct", v.get("tkl_pct", 0)))
    made     = v.get("tkl_made", 0)
    att      = v.get("tkl_att", 0)
    count    = v.get("int_count", 0)
    pass_att = v.get("pass_att", 0)
    remaining = max(att - made, 0) if att > 0 else 0

    # ── Combo triggers (override normal pool) ────────────────
    template = None
    if rtype == "conversion" and shots >= 6 and pct < 20:
        template = random.choice(_COMBO_ROASTS["finishing_collapse"])
    elif shots == 0 and pass_att > 0 and pass_att < 6 and count == 0:
        template = random.choice(_COMBO_ROASTS["ghost"])
    elif rtype == "conversion" and shots >= 5 and assists == 0:
        template = random.choice(_COMBO_ROASTS["selfish"])

    # ── Normal tiered selection ───────────────────────────────
    if template is None:
        if registry and rtype in registry.get("roasts", {}):
            pool = registry["roasts"][rtype]
        else:
            pool = _UNKNOWN_ROASTS.get(rtype, _UNKNOWN_ROASTS["passing"])

        tier = _get_tier(rtype, pct)
        n    = len(pool)
        if tier == "nuclear":
            template = random.choice(pool[max(0, n - max(n // 3, 1)):])
        elif tier == "heavy":
            template = random.choice(pool[n // 3: max(n // 3 + 1, 2 * n // 3)])
        else:
            template = random.choice(pool[:max(n // 2, 1)])

    # ── Format ───────────────────────────────────────────────
    roast = template.format(
        name=name, pct=pct, shots=shots, goals=goals, assists=assists,
        made=made, attempted=att, count=count,
        pass_att=pass_att, remaining=remaining,
    )

    # ── Rare special event intro (10% chance) ─────────────────
    if random.random() < 0.10:
        roast = random.choice(_SPECIAL_EVENTS) + roast

    # ── Occasional extra kicker (20% chance) ──────────────────
    if random.random() < 0.20:
        roast += "\n\n*" + random.choice(_EXTRA_LINES) + "*"

    return roast


def _roast_title(rtype: str) -> str:
    return {
        "passing":       "Passing Roast",
        "conversion":    "Conversion Rate Roast",
        "tackling":      "Tackling Roast",
        "interceptions": "Interception Roast",
        "low_passes":    "Get On The Ball",
    }.get(rtype, "Stat Roast")


def _footer_stat(rtype: str, v: dict) -> str:
    if rtype == "passing":
        return f"{v.get('pass_pct')}% pass accuracy ({v.get('passes_completed','?')}/{v.get('passes_attempted','?')})"
    if rtype == "conversion":
        return f"{v.get('conv_pct')}% conversion ({v.get('goals','?')}/{v.get('shots','?')} shots)"
    if rtype == "tackling":
        return f"{v.get('tkl_pct')}% tackle success ({v.get('tkl_made','?')}/{v.get('tkl_att','?')})"
    if rtype == "interceptions":
        return f"{v.get('int_count')} interceptions"
    if rtype == "low_passes":
        return f"{v.get('pass_att')} passes attempted ({v.get('pass_pct')}% accuracy)"
    return ""


# Position → player mapping for when name OCR fails
# Positions in OurProClub are consistent per player
_POSITION_TO_PLAYER: dict[str, str] = {
    "attacking target":    "RoyalBannaJi",
    "attacking finisher":  "RoyalBannaJi",
    "midfield spark":      "RoyalBannaJi",
    "attacking spark":     "ShreyChoudhary98",
    "midfield finisher":   "jashnasalvi",
    "midfield magician":   "PJ10 x",
    "midfield creator":    "ChachaToji",
    "midfield maestro":    "Chitraksh08",
    "midfield recycler":   "Chitraksh08",
    "defensive boss":      "itspaynewhackhim",
    "defensive mid":       "itspaynewhackhim",
    "midfield spark":      "ShreyChoudhary98",
    "box to box":          "ChachaToji",
    "second striker":      "ShreyChoudhary98",
    "winger":              "ShreyChoudhary98",
}

# OCR name aliases — maps garbled in-game names to registry keys
_NAME_ALIASES: dict[str, str] = {
    "vishwak12":  "vishwask12",
    "vishwas12":  "vishwask12",
    "pj10x":      "PJ10 x",
    "pj10":       "PJ10 x",
}


def _fuzzy_lookup(name: str, position: str = "") -> dict | None:
    """Case-insensitive + partial + similarity match against player registry."""
    import re as _re

    if name in PLAYER_REGISTRY:
        return PLAYER_REGISTRY[name]

    # Check aliases
    aliased = _NAME_ALIASES.get(name) or _NAME_ALIASES.get(name.lower())
    if aliased and aliased in PLAYER_REGISTRY:
        return PLAYER_REGISTRY[aliased]

    # Strip trailing OCR noise — keep only alphanumeric + spaces up to the core name
    # "PJ10x Ye" → try "PJ10x" first, "cosmicfps06 BE" → "cosmicfps06"
    name_stripped = _re.split(r'[ ]+[A-Z][a-z]', name)[0].strip()  # strip trailing "Ye", "BE" etc
    name_stripped = _re.sub(r'[^A-Za-z0-9 _]', '', name_stripped).strip()

    candidates = list(dict.fromkeys([name, name_stripped]))  # try both, deduped

    for candidate in candidates:
        name_lower = candidate.lower().strip()

        # Exact case-insensitive
        for key, val in PLAYER_REGISTRY.items():
            if key.lower() == name_lower:
                return val

        # Prefix match
        for key, val in PLAYER_REGISTRY.items():
            kl = key.lower()
            if name_lower.startswith(kl) or kl.startswith(name_lower):
                return val

        # Similarity match
        best_ratio = 0.0
        best_val   = None
        for key, val in PLAYER_REGISTRY.items():
            kl     = key.lower()
            common = sum(1 for a, b in zip(name_lower, kl) if a == b)
            ratio  = common / max(len(name_lower), len(kl), 1)
            if ratio > best_ratio:
                best_ratio = ratio
                best_val   = val

        if best_ratio >= 0.65:
            return best_val

    # Position-based fallback — if name totally unrecognised, use position
    if position:
        player_name = _POSITION_TO_PLAYER.get(position.lower().strip())
        if player_name and player_name in PLAYER_REGISTRY:
            return PLAYER_REGISTRY[player_name]

    return None


# ─────────────────────────────────────────────────────────────────────────────
# !roast command — fun roasts using real lifetime stats
# ─────────────────────────────────────────────────────────────────────────────

# Maps Discord user ID → in-game name
DISCORD_TO_PLAYER: dict[str, str] = {
    v["discord_id"]: k for k, v in PLAYER_REGISTRY.items()
}

# Each entry: (stat_getter, roast_templates)
# stat_getter receives the lifetime stats dict and returns a display value
# templates receive **kwargs with the computed values

_FUN_ROASTS: list[dict] = [
    {
        "key": "goals_per_game",
        "compute": lambda s: {
            "gpg":     round(s.get("goals", 0) / max(s.get("matches", 1), 1), 2),
            "goals":   s.get("goals", 0),
            "matches": s.get("matches", 1),
        },
        "templates": [
            "{goals} goals in {matches} games. {gpg} per game. Incredible consistency — consistently bad.",
            "Career average of {gpg} goals per game. Some players score hat-tricks. You score {gpg}.",
            "{gpg} goals per game across {matches} matches. The goal drought is not a drought — it's a desert.",
            "{goals} goals in {matches} games. Maths says {gpg} per game. Football says find a new hobby.",
            "Lifetime goals: {goals}. Lifetime games: {matches}. Lifetime average: {gpg}. Lifetime regrets: uncountable.",
            "{gpg} goals per game. At this rate you'll hit double figures sometime around 2031.",
        ],
    },
    {
        "key": "pass_accuracy",
        "compute": lambda s: {
            "pct":       round(s.get("passes_completed", 0) / max(s.get("passes_attempted", 1), 1) * 100),
            "completed": s.get("passes_completed", 0),
            "attempted": s.get("passes_attempted", 1),
        },
        "templates": [
            "Career pass accuracy: {pct}%. {completed} out of {attempted}. The rest went to the other team as gifts.",
            "{pct}% career passing. The opposition's pass accuracy improved significantly every time you played.",
            "{completed} passes completed out of {attempted} attempts. Career {pct}%. A GPS would not help you.",
            "Lifetime passing: {pct}%. You've been playing long enough to fix this. You haven't.",
            "{attempted} career pass attempts. {completed} found a teammate. {pct}%. The rest found new friends.",
            "Career {pct}% passing accuracy. Even autocorrect has a higher success rate than you.",
        ],
    },
    {
        "key": "tackle_ratio",
        "compute": lambda s: {
            "tkl":     s.get("tackles", 0),
            "matches": s.get("matches", 1),
            "tpm":     round(s.get("tackles", 0) / max(s.get("matches", 1), 1), 2),
        },
        "templates": [
            "{tkl} career tackles in {matches} games. {tpm} per game. The grass is more aggressive than you.",
            "Career tackles: {tkl} in {matches} matches. {tpm} per game. The kit man defends more than you.",
            "{tpm} tackles per game over a {matches}-game career. A traffic cone would have the same impact.",
            "{tkl} tackles in {matches} games. That's {tpm} per match. Referees have made more tackles.",
            "Career defensive output: {tkl} tackles, {tpm} per game. The substitutes' bench is more disruptive.",
            "{tpm} tackles per game. Some players press. Some players defend. You exist.",
        ],
    },
    {
        "key": "assists",
        "compute": lambda s: {
            "ast":     s.get("assists", 0),
            "matches": s.get("matches", 1),
            "apm":     round(s.get("assists", 0) / max(s.get("matches", 1), 1), 2),
        },
        "templates": [
            "{ast} career assists in {matches} games. {apm} per game. The ball prefers other feet.",
            "Lifetime assists: {ast}. Lifetime games: {matches}. {apm} per match. The 'team player' label is under review.",
            "{apm} assists per game. Kevin De Bruyne cried reading this. Then scored a hat-trick of assists in one half.",
            "{ast} assists over {matches} matches. The strikers have been self-sufficient out of necessity.",
            "Career {apm} assists per game. You've been on the pitch {matches} times and found a teammate {ast} times.",
            "{ast} assists in {matches} games. The striker emoji in the group chat is about to get personal.",
        ],
    },
    {
        "key": "rating",
        "compute": lambda s: {
            "avg":     round(s.get("rating_total", 0) / max(s.get("matches", 1), 1), 2),
            "matches": s.get("matches", 1),
            "total":   round(s.get("rating_total", 0), 1),
        },
        "templates": [
            "Career average rating: {avg}. EA has seen you play {matches} games and still rates you {avg}.",
            "{avg} average rating across {matches} matches. The match rating system only goes down to 3.0. You've tested the floor.",
            "Lifetime average: {avg}/10. The 10 is doing a lot of heavy lifting there.",
            "{avg} career average rating. The match of the week has never, not once, been you.",
            "After {matches} games, EA rates you {avg} on average. The algorithm has seen enough.",
            "{avg} average rating over {matches} games. Consistent. Consistently {avg}.",
        ],
    },
    {
        "key": "crowns_vs_curses",
        "compute": lambda s: {
            "crowns":  s.get("crowns", 0),
            "curses":  s.get("curses", 0),
            "matches": s.get("matches", 1),
        },
        "templates": [
            "{crowns} crowns and {curses} curses across {matches} games. The chaos bot knows you too well.",
            "Career record: {crowns} crowns, {curses} curses. The curses are winning.",
            "{curses} curses in {matches} games. The chaos engine has a dedicated folder for you.",
            "{crowns} crowns vs {curses} curses. The numbers don't lie — and neither does the chaos bot.",
            "Lifetime: {crowns} crowns, {curses} curses. You're not cursed, you're consistent. Consistently cursed.",
            "{curses} career curses. The chaos bot saw you coming {matches} games ago and started taking notes.",
        ],
    },
    {
        "key": "shots_vs_goals",
        "compute": lambda s: {
            "shots":   s.get("shots", 0),
            "goals":   s.get("goals", 0),
            "wasted":  s.get("shots", 0) - s.get("goals", 0),
            "conv":    round(s.get("goals", 0) / max(s.get("shots", 1), 1) * 100),
        },
        "templates": [
            "{shots} career shots. {goals} goals. {wasted} misses. {conv}% conversion. The goalkeeper has a shrine dedicated to you.",
            "Career: {shots} shots, {goals} goals. That's {wasted} times the ball went somewhere wrong. {conv}% conversion.",
            "{conv}% career conversion rate from {shots} shots. The woodwork has more goals than you.",
            "{wasted} shots wasted over your career. The net is still waiting to get properly acquainted with you.",
            "{shots} shots, {goals} goals, {conv}% conversion. The concept of finishing is aware of you. You are not aware of it.",
            "Career conversion: {conv}%. {wasted} wasted shots. The goalkeeper sends their regards and a thank you card.",
        ],
    },
]

# Generic fallbacks if player has very few games
_FUN_ROASTS_LOW_GAMES = [
    "{name} has only played {matches} games with us. Even the opposition doesn't remember you yet.",
    "{matches} appearances for {name}. The squad photo doesn't have enough room for someone so part-time.",
    "{name}. {matches} games in. The kit still fits because it barely gets worn.",
    "After {matches} games, {name} remains a mystery to the opposition. And the team. And everyone.",
    "{matches} appearances. {name} is technically on the team. Technically.",
]


def get_fun_roast(discord_id: str, lifetime_stats: dict) -> tuple[str, str]:
    """
    Generate a fun roast for a player based on their lifetime stats.

    Returns (mention_str, roast_text).
    """
    # Resolve Discord ID → player name
    name = DISCORD_TO_PLAYER.get(str(discord_id))
    if name:
        mention = f"<@{discord_id}>"
    else:
        mention = f"<@{discord_id}>"
        name    = "Mystery Player"

    # Look up lifetime stats by name (fuzzy)
    stats = _fuzzy_stats_lookup(name, lifetime_stats)

    if not stats or stats.get("matches", 0) < 3:
        matches = stats.get("matches", 0) if stats else 0
        roast   = random.choice(_FUN_ROASTS_LOW_GAMES).format(name=name, matches=matches)
        return mention, roast

    # Pick a random roast category, compute values, render template
    category = random.choice(_FUN_ROASTS)
    values   = category["compute"](stats)
    roast    = random.choice(category["templates"]).format(**values)

    return mention, roast


def _fuzzy_stats_lookup(name: str, all_stats: dict) -> dict | None:
    if name in all_stats:
        return all_stats[name]
    name_lower = name.lower()
    for key, val in all_stats.items():
        if key.lower() == name_lower:
            return val
    for key, val in all_stats.items():
        if key.lower().startswith(name_lower) or name_lower.startswith(key.lower()):
            return val
    # Position-based fallback — if name totally unrecognised, use position
    if position:
        player_name = _POSITION_TO_PLAYER.get(position.lower().strip())
        if player_name and player_name in PLAYER_REGISTRY:
            return PLAYER_REGISTRY[player_name]

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Praise engine
# ─────────────────────────────────────────────────────────────────────────────

# Thresholds for praise
PRAISE_PASS_THRESHOLD    = 88   # % — min 5 attempts
PRAISE_CONV_THRESHOLD    = 60   # % — min 3 shots
PRAISE_TACKLE_THRESHOLD  = 70   # % — min 5 attempts
PRAISE_INT_THRESHOLD     = 5    # count
PRAISE_RATING_THRESHOLD  = 9.0
PRAISE_ASSIST_THRESHOLD  = 3

_PRAISE_POOL: dict[str, dict[str, list[str]]] = {
    "RoyalBannaJi": {
        "passing":    ["Immaculate in possession tonight. {pct}% passing — the main character delivered with the ball too.", "RoyalBannaJi was pinging it around like he owned the pitch. {pct}% passing. The vision was there.", "Main character energy AND {pct}% passing accuracy. Rare combination. Respect.", "{pct}% passing from the striker. The team played through him and it worked."],
        "conversion": ["Clinical. Absolutely clinical. {goals} goals from {shots} shots — {pct}% conversion. The goalkeeper didn't stand a chance.", "That's the RoyalBannaJi we know. {goals} from {shots} — {pct}% conversion rate. Ice in the veins.", "{pct}% conversion tonight. When he hits the target, it goes in. Simple as.", "Main character syndrome fully justified tonight. {goals} goals, {pct}% conversion. Carry on."],
        "rating":     ["A {rating} rating tells the story. RoyalBannaJi was unplayable tonight.", "Man of the match. No arguments. {rating} on the night — the opposition couldn't handle him.", "{rating}. On another level tonight. The team rides on his shoulders."],
        "assists":    ["{assists} assists from a striker is just showing off. The link-up play was brilliant.", "RoyalBannaJi pulling strings tonight with {assists} assists. More than just a goal threat.", "{assists} assists. Main character decided to share the spotlight tonight. Big of him."],
    },
    "PJ10 x": {
        "passing":    ["{pct}% passing. The Midfield Magician was in full flow — the ball moved like water.", "That's the tiki-taka we've been waiting for. PJ10 at {pct}% — just magical.", "PJ10 x with {pct}% passing accuracy. Pep would be proud. Genuinely.", "The possession game was built through PJ10 tonight. {pct}% — metronomic."],
        "tackling":   ["{pct}% tackle success from the possession midfielder — brilliant two-way performance.", "PJ10 x winning the ball back at {pct}% — doing the dirty work AND the pretty stuff.", "{made} from {attempted} tackles at {pct}%. The Magician with defensive steel too."],
        "interceptions": ["{count} interceptions — PJ10 reading the game like a chess grandmaster.", "The Midfield Magician sniffed out danger {count} times. The interceptions were as good as the passes.", "{count} interceptions from the man pulling the strings. Complete midfield performance."],
        "assists":    ["{assists} assists. PJ10 x orchestrating the attack — this is what he's built for.", "The Midfield Magician lived up to the name tonight. {assists} assists — the team played through him.", "{assists} key passes converted. PJ10 was undroppable tonight."],
    },
    "ShreyChoudhary98": {
        "passing":    ["{pct}% passing from Shrey — the link-up play was seamless tonight.", "ShreyChoudhary98 knitting things together at {pct}% — exactly what the second striker should do.", "Shrey was the connective tissue tonight. {pct}% passing, always available, always sharp."],
        "conversion": ["ShreyChoudhary98 making his shots count — {goals} from {shots}, {pct}% conversion.", "{pct}% conversion rate. Shrey was clinical when it mattered.", "The Midfield Finisher finishing like a striker tonight. {goals} goals, {pct}% conversion."],
        "assists":    ["{assists} assists from Shrey — the second striker role played to perfection.", "Creating and scoring — {assists} assists from ShreyChoudhary98 tonight. Excellent.", "Shrey pulling the strings with {assists} assists. The midfield-attack link was him."],
        "rating":     ["{rating} for ShreyChoudhary98 — a complete performance from the versatile one.", "Shrey was everywhere tonight and everywhere was good. {rating} rating well deserved."],
    },
    "itspaynewhackhim": {
        "passing":    ["The safe passer living up to the name — {pct}% tonight. No risks, all rewards.", "{pct}% passing accuracy. Itspaynewhackhim was the metronome the team needed.", "Safe passes AND effective ones. {pct}% — the defensive midfielder bossing the build-up."],
        "tackling":   ["Itspaynewhackhim was a brick wall tonight. {pct}% tackle success — {made} from {attempted}.", "{pct}% tackle success. The safe passer was anything but safe to play against.", "The Defensive Boss earning that title tonight. {made} tackles won at {pct}% — superb."],
        "interceptions": ["{count} interceptions — itspaynewhackhim reading the game brilliantly.", "The defensive midfielder intercepting {count} times. Exactly what the role demands.", "{count} interceptions. Itspaynewhackhim was everywhere the ball wasn't supposed to go."],
        "rating":     ["{rating} for the Defensive Boss — a commanding performance.", "You cannot ask more from a defensive midfielder. {rating} rating, dominant all night."],
    },
    "cosmicfps06": {
        "passing":    ["{pct}% passing — cosmic proving the skill moves come with substance too.", "cosmicfps06 threading passes at {pct}% — the creativity had a foundation tonight.", "Not just tricks tonight — {pct}% passing accuracy from the skill moves merchant. The full package."],
        "conversion": ["The skill moves AND the finish — {goals} from {shots}, {pct}% conversion. Lethal.", "{pct}% conversion rate. cosmicfps06 turned the tricks into goals tonight.", "Every step-over had a purpose tonight. {goals} goals, {pct}% conversion. Spectacular."],
        "assists":    ["{assists} assists — cosmicfps06 making teammates look good too, not just himself.", "The skill moves created {assists} assists tonight. The flair had a point after all.", "{assists} key contributions. cosmicfps06 was unplayable tonight."],
        "rating":     ["{rating} for cosmicfps06 — the showman delivered the substance tonight.", "When cosmicfps06 is on form, he's a nightmare to deal with. {rating} — on form tonight."],
    },
    "metalstone_11": {
        "passing":    ["{pct}% passing — the up and coming kid showing maturity beyond his experience.", "metalstone_11 with {pct}% passing accuracy — the glory moment came through the simple things.", "The kid is growing into this. {pct}% passing — composed and effective."],
        "conversion": ["The glory moment arrived — {goals} goals from {shots} shots at {pct}%. metalstone_11 delivered.", "{pct}% conversion rate. The hunger for glory turned into actual goals tonight. Brilliant.", "metalstone_11 making his shots count at {pct}% — the young gun is finding his range."],
        "assists":    ["{assists} assists from the youngster — the come-up story is coming up nicely.", "metalstone_11 with {assists} assists — the glory moment was shared tonight. Growing up.", "The up and coming kid setting up {assists} goals. Coming up fast."],
        "rating":     ["{rating} for metalstone_11 — a statement performance from the youngster.", "The kid delivered tonight. {rating} rating — the squad is taking notice."],
    },
    "Chitraksh08": {
        "passing":    ["{pct}% passing from the CDM — Chitraksh was the platform everything was built on.", "The recycler recycling brilliantly — {pct}% passing accuracy. Flawless distribution.", "Chitraksh08 at {pct}% passing — the engine room was purring tonight."],
        "tackling":   ["Chitraksh08 dominant in the tackle — {pct}% success rate, {made} from {attempted}. Immense.", "The CDM doing CDM things. {pct}% tackle success — the defensive shield was up tonight.", "{made} tackles won at {pct}%. Chitraksh was a one-man wall in the middle."],
        "interceptions": ["{count} interceptions — Chitraksh reading the game like a seasoned pro.", "The Midfield Maestro living up to the name with {count} interceptions. Dominant.", "{count} interceptions from Chitraksh08. Everywhere the opposition tried to play, he was there."],
        "rating":     ["{rating} for Chitraksh08 — the CDM was the best player on the pitch tonight.", "Complete CDM performance. {rating} rating — penalty taker, ball winner, distributor. The lot."],
    },
    "jashnasalvi": {
        "passing":    ["{pct}% passing from the goal-hungry attacker — the link-up was there too tonight.", "jashnasalvi making the simple pass and making it count. {pct}% accuracy.", "Goals first AND good passing — {pct}% from jashnasalvi. The complete forward tonight."],
        "conversion": ["jashnasalvi in front of goal — {goals} from {shots} at {pct}%. This is why he plays.", "{pct}% conversion rate. The attack-oriented player was clinical tonight. Goals first, goals delivered.", "The hunger for goals justified tonight. {goals} goals, {pct}% conversion. Ruthless."],
        "assists":    ["{assists} assists from the goal hunter — jashnasalvi was setting others up too tonight.", "Goals first but assists too — {assists} from jashnasalvi. Unselfish when it counted.", "{assists} assists. The attack-oriented player spreading the joy tonight."],
        "rating":     ["{rating} for jashnasalvi — when he's on it, he's really on it.", "The goal-hungry attacker satisfied his hunger tonight. {rating} — a brilliant display."],
    },
    "ChachaToji": {
        "passing":    ["The most versatile player passing like the most clinical one — {pct}% accuracy. Outstanding.", "ChachaToji at {pct}% passing — the overcooked nights forgotten when he plays like this.", "Versatility on full display — {pct}% passing accuracy. ChachaToji was exceptional tonight."],
        "tackling":   ["{pct}% tackle success from ChachaToji — the versatility extended to winning the ball.", "ChachaToji winning tackles at {pct}% — the all-rounder doing everything right tonight.", "{made} from {attempted} tackles at {pct}%. ChachaToji in complete control."],
        "assists":    ["{assists} assists — the most versatile player showing his most versatile performance.", "ChachaToji setting up {assists} goals tonight. The range of his game is remarkable.", "{assists} assists from ChachaToji. When he doesn't overcook it, he's magnificent."],
        "rating":     ["{rating} for ChachaToji — the versatile player putting it all together tonight.", "This is the ChachaToji the squad knows is possible. {rating} — complete performance."],
    },
    "vishwask12": {
        "passing":    ["{pct}% passing from the Spark — the creativity had a solid base tonight.", "vishwak12 igniting things with {pct}% passing accuracy. The Spark sparked right.", "The Midfield Spark with {pct}% passing — lighting up the midfield in every way."],
        "conversion": ["vishwak12 making shots count at {pct}% conversion — the Spark turned into fire.", "{goals} from {shots} at {pct}% — vishwak12 was a constant threat and delivered.", "The Spark making his shots count — {pct}% conversion rate, {goals} goals. Brilliant."],
        "assists":    ["{assists} assists from vishwak12 — the Spark ignited the attack tonight.", "The Midfield Spark setting up {assists} goals. The creativity was real tonight.", "{assists} assists from vishwak12 — the team fed off his energy and his passes."],
        "rating":     ["{rating} for vishwak12 — the Spark earned every decimal point of that rating.", "vishwak12 on fire tonight. {rating} — this is what the Spark looks like at full voltage."],
    },
}

# Caution messages for low pass volume (used alongside praise)
_LOW_PASS_CAUTIONS: dict[str, list[str]] = {
    "RoyalBannaJi":     ["Only {pass_att} passes though. The main character needs more involvement. Be brave.", "{pass_att} passes from the striker. The team needs you on the ball more.", "Come on. {pass_att} passes. Main character or not — get involved."],
    "PJ10 x":           ["Only {pass_att} passes from the possession midfielder. That's not possession. Be brave, get on the ball.", "{pass_att} passes. The tiki-taka needs more tiki. Get involved.", "Come on PJ10. {pass_att} passes. The team needs you to demand the ball more."],
    "ShreyChoudhary98": ["{pass_att} passes from the link player. The link was barely connected. Be bold.", "Only {pass_att} passes — Shrey needs to be more available. Come on.", "Be brave. {pass_att} passes. The second striker needs to show for the ball more."],
    "itspaynewhackhim": ["{pass_att} passes. Safe passer attempting {pass_att} passes — that's not safe, that's invisible. Get on the ball.", "Only {pass_att} passes. Be bold. The safe option is to actually receive the ball first.", "Come on. {pass_att} passes. Defensive midfielder or ghost? Get involved."],
    "cosmicfps06":       ["{pass_att} passes. The skill moves need a foundation. Be brave, demand the ball.", "Only {pass_att} passes from the skill moves merchant. Hard to do step-overs without the ball.", "Come on. {pass_att} passes. Get on the ball more and then do the tricks."],
    "metalstone_11":     ["Only {pass_att} passes. The glory moment won't come if you don't get on the ball. Be brave.", "{pass_att} passes from the youngster. The come-up requires more involvement. Come on.", "Be bold. {pass_att} passes. The up and coming kid needs to show up more."],
    "Chitraksh08":       ["{pass_att} passes from the CDM. The engine room was barely ticking. Demand the ball.", "Only {pass_att} passes. Be brave. A CDM who doesn't pass isn't distributing — they're hiding.", "Come on Chitraksh. {pass_att} passes. The recycler needs more material to work with."],
    "jashnasalvi":       ["Goals first, but {pass_att} passes means you weren't involved enough. Be brave.", "Only {pass_att} passes. The attack-oriented player needs to attack more situations. Get on the ball.", "Come on. {pass_att} passes. You can't score if you don't get the ball. Be bold."],
    "ChachaToji":        ["{pass_att} passes. The most versatile player was barely visible. Be brave, get involved.", "Only {pass_att} passes from ChachaToji. The versatility needs a foundation of involvement. Come on.", "Be bold. {pass_att} passes. Versatile players show for the ball — they don't hide from it."],
    "vishwak12":         ["{pass_att} passes. The Spark needs to ignite more. Be brave, demand the ball.", "Only {pass_att} passes from the Midfield Spark. Hard to spark without touching the ball. Come on.", "Be bold. {pass_att} passes. The Spark needs more contact with the ball to light things up."],
}

_DEFAULT_LOW_PASS_CAUTION = [
    "Only {pass_att} passes though. Be brave. Get on the ball more.",
    "{pass_att} passes. Come on — be bold, demand the ball.",
    "A word of caution: only {pass_att} passes. Don't be a ghost. Get involved.",
    "Be brave. {pass_att} passes is not enough. The team needs you on the ball.",
]

_UNKNOWN_PRAISES: dict[str, list[str]] = {
    "passing":    ["{name} with {pct}% passing tonight — whoever you are, that was impressive.", "Don't know much about {name} but {pct}% passing speaks for itself.", "{pct}% passing from {name}. A solid debut performance. Come back more often."],
    "conversion": ["{name} — {goals} goals from {shots} shots at {pct}% conversion. Making a case for regular football.", "{pct}% conversion from {name}. The irregular player made the most of his chances.", "{goals} goals, {pct}% conversion from {name}. We should see more of this player."],
    "tackling":   ["{name} winning tackles at {pct}% — impressive for someone who doesn't play regularly.", "{pct}% tackle success from {name}. The squad could use that defensive energy more often.", "{made} from {attempted} tackles — {name} was excellent. Play more regularly."],
    "interceptions": ["{name} intercepting {count} times — reading the game well for an irregular player.", "{count} interceptions from {name}. The game awareness was sharp tonight.", "Didn't expect {count} interceptions from {name} but here we are. Well played."],
    "rating":     ["{name} with a {rating} tonight — the irregular player had a very regular quality performance.", "{rating} for {name}. Whoever books these players, book this one again.", "A {rating} from {name}. Outstanding. Now play regularly."],
    "assists":    ["{assists} assists from {name} — making a strong case for more game time.", "{name} setting up {assists} goals tonight. The squad needs this energy more often.", "{assists} assists from the irregular player {name}. Exceptional contribution."],
}


def get_praise_candidates(players: list[dict]) -> list[dict]:
    """Return players who deserve praise based on their stats."""
    praised = []
    for p in players:
        reasons = []
        name = p.get("name", "")
        att  = p.get("passes_attempted", 0)
        comp = p.get("passes_completed", 0)
        shots  = p.get("shots", 0)
        goals  = p.get("goals", 0)
        tkl_att  = p.get("tackles_attempted", 0)
        tkl_made = p.get("tackles", 0)
        ints   = p.get("interceptions", 0)
        rating = p.get("rating", 0.0)
        assists = p.get("assists", 0)

        if att >= 5:
            pct = round(comp / att * 100)
            if pct >= PRAISE_PASS_THRESHOLD:
                reasons.append({"type": "passing", "pct": pct})

        if shots >= 3:
            conv = round(goals / shots * 100)
            if conv >= PRAISE_CONV_THRESHOLD:
                reasons.append({"type": "conversion", "conv_pct": conv, "shots": shots, "goals": goals})

        if tkl_att >= 5:
            tpct = round(tkl_made / tkl_att * 100)
            if tpct >= PRAISE_TACKLE_THRESHOLD:
                reasons.append({"type": "tackling", "tkl_pct": tpct, "tkl_made": tkl_made, "tkl_att": tkl_att})

        if ints >= PRAISE_INT_THRESHOLD:
            reasons.append({"type": "interceptions", "count": ints})

        if rating >= PRAISE_RATING_THRESHOLD:
            reasons.append({"type": "rating", "rating": rating})

        if assists >= PRAISE_ASSIST_THRESHOLD:
            reasons.append({"type": "assists", "assists": assists})

        if reasons:
            # Check for low pass volume — add as caution alongside praise
            caution = None
            if att >= 3 and att < LOW_PASS_MAX_ATT and reasons:
                caution = {"type": "low_pass_caution", "pass_att": att}
            praised.append({**p, "praise_reasons": reasons, "caution": caution})

    return praised


def _pick_praise(registry, name, rtype, v) -> str:
    pct     = v.get("pct", v.get("conv_pct", v.get("tkl_pct", 0)))
    shots   = v.get("shots", 0)
    goals   = v.get("goals", 0)
    made    = v.get("tkl_made", 0)
    att     = v.get("tkl_att", 0)
    count   = v.get("count", 0)
    rating  = v.get("rating", 0.0)
    assists = v.get("assists", 0)

    player_praises = _PRAISE_POOL.get(name, {}) if registry else {}
    pool = player_praises.get(rtype) or _UNKNOWN_PRAISES.get(rtype, [])
    template = random.choice(pool) if pool else f"{name} had a great {rtype} performance."

    return template.format(
        name=name, pct=pct, shots=shots, goals=goals,
        made=made, attempted=att, count=count,
        rating=rating, assists=assists,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Silent treatment — boring game detection
# ─────────────────────────────────────────────────────────────────────────────

_SILENT_TREATMENT = [
    "🎙️ The panel has requested silence.\nWe will not be discussing this performance.",
    "🎙️ Our analysts have reviewed the footage and chosen to go home early.\nNo further comment.",
    "🎙️ The studio has gone quiet.\nThe producers have nothing to work with tonight.",
    "🎙️ After careful deliberation, the panel has agreed: this match did not happen.\nWe move on.",
    "🎙️ The pundits have left the building.\nSo has the entertainment.",
    "🎙️ We asked the panel for their thoughts.\nThey said nothing. For the first time in their careers, nothing.",
    "🎙️ The highlight reel has been reviewed.\nThere are no highlights.",
    "🎙️ This is the part of the show where we discuss standout moments.\nWe will be skipping this part.",
    "🎙️ Gary Neville has turned off his microphone.\nJamie Carragher is staring at the wall.\nNo comment from either.",
    "🎙️ The panel convened. Reviewed the stats. Closed their notebooks.\nSome performances speak for themselves. This one chose not to speak.",
]


def is_boring_game(
    players: list[dict],
    results: list,           # achievements.PlayerResult list
    match_data: dict,
) -> bool:
    """Return True if the game qualifies for the silent treatment."""
    if not players:
        return False

    # Condition 1: Win but everyone rated below 7.5
    result = match_data.get("result", "")
    if result == "Win":
        if all(p.get("rating", 0) < 7.5 for p in players):
            return True

    # Condition 2: Team scored but no individual standout stat
    # Standout = goal, assist, 2+ interceptions, 80%+ passing (min 10), rating 8+
    team_goals = sum(p.get("goals", 0) for p in players)
    if team_goals > 0:
        def _has_standout(p):
            att = p.get("passes_attempted", 0)
            pas_pct = p["passes_completed"] / att * 100 if att >= 10 else 0
            return (
                p.get("goals", 0) > 0
                or p.get("assists", 0) > 0
                or p.get("interceptions", 0) >= 2
                or pas_pct >= 80
                or p.get("rating", 0) >= 8.0
            )
        if not any(_has_standout(p) for p in players):
            return True

    # Condition 3: No crowns/powers/praise — only curses or roasts
    if results:
        has_crown  = any(r["achievements"] for r in results)
        if not has_crown:
            victims  = get_roast_victims(players)
            praised  = get_praise_candidates(players)
            # Only roasts/curses, no crowns, no praise = boring
            if not praised and victims and not has_crown:
                has_curse = any(r["curses"] for r in results)
                if has_curse or victims:
                    return True

    return False


def build_silent_treatment_embed(match_data: dict) -> discord.Embed:
    """Build the silent treatment embed for boring games."""
    score    = match_data.get("score", "?")
    opponent = match_data.get("opponent", "Unknown")
    line     = random.choice(_SILENT_TREATMENT)

    embed = discord.Embed(
        title="📺 Pundit Verdict",
        description=line,
        colour=discord.Colour.dark_gray() if hasattr(discord.Colour, "dark_gray") else discord.Colour.default(),
    )
    embed.set_footer(text=f"{score} vs {opponent}")
    return embed
