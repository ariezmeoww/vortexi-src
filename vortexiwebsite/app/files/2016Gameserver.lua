local PlaceId, Port, BaseURL, AuthToken, CreatorId, CreatorType, DownloadAuthorizationToken = ...

local RunService = game:GetService("RunService")
local ContentProvider = game:GetService("ContentProvider")
local Players = game:GetService("Players")
local HttpService = game:GetService("HttpService")
local ScriptContext = game:GetService('ScriptContext')
local RobloxReplicatedStorage = game:GetService('RobloxReplicatedStorage')

HttpService.HttpEnabled = false -- Disable HttpService for security reasons

if CreatorType == 1 then
    CreatorType = Enum.CreatorType.User
elseif CreatorType == 2 then
    CreatorType = Enum.CreatorType.Group
else
    CreatorType = Enum.CreatorType.User
end
pcall(function() game:SetCreatorID(CreatorId, CreatorType) end)

pcall(function() settings().Network.UseInstancePacketCache = true end)
pcall(function() settings().Network.UsePhysicsPacketCache = true end)
--pcall(function() settings()["Task Scheduler"].PriorityMethod = Enum.PriorityMethod.FIFO end)
pcall(function() settings()["Task Scheduler"].PriorityMethod = Enum.PriorityMethod.AccumulatedError end)

--settings().Network.PhysicsSend = 1 -- 1==RoundRobin
--settings().Network.PhysicsSend = Enum.PhysicsSendMethod.ErrorComputation2
settings().Network.PhysicsSend = Enum.PhysicsSendMethod.TopNErrors
settings().Network.ExperimentalPhysicsEnabled = true
settings().Network.WaitingForCharacterLogRate = 100
pcall(function() settings().Diagnostics:LegacyScriptMode() end)

pcall(function() ScriptContext:AddStarterScript(37801172) end)
ScriptContext.ScriptsDisabled = true

game:SetPlaceID(PlaceId, false)
game:GetService("ChangeHistoryService"):SetEnabled(false)
local NetworkServer = game:GetService("NetworkServer")

if BaseURL~=nil then
	pcall(function() game:GetService("Players"):SetAbuseReportUrl(BaseURL .. "/AbuseReport/InGameChatHandler.ashx") end)
	pcall(function() game:GetService("ScriptInformationProvider"):SetAssetUrl(BaseURL .. "/Asset/") end)
	pcall(function() game:GetService("ContentProvider"):SetBaseUrl(BaseURL .. "/") end)
	pcall(function() game:GetService("Players"):SetChatFilterUrl(BaseURL .. "/Game/ChatFilter.ashx") end)

	game:GetService("BadgeService"):SetPlaceId(PlaceId)
	game:GetService("BadgeService"):SetIsBadgeLegalUrl("")
    game:GetService("BadgeService"):SetAwardBadgeUrl(BaseURL .. "/Game/Badge/AwardBadge.ashx?UserID=%d&BadgeID=%d&PlaceID=%d")
    game:GetService("BadgeService"):SetHasBadgeUrl(BaseURL .. "/Game/Badge/HasBadge.ashx?UserID=%d&BadgeID=%d")
	game:GetService("BadgeService"):SetIsBadgeDisabledUrl(BaseURL .. "/Game/Badge/IsBadgeDisabled.ashx?BadgeID=%d&PlaceID=%d")

	game:GetService("InsertService"):SetBaseSetsUrl(BaseURL .. "/Game/Tools/InsertAsset.ashx?nsets=10&type=base")
	game:GetService("InsertService"):SetUserSetsUrl(BaseURL .. "/Game/Tools/InsertAsset.ashx?nsets=20&type=user&userid=%d")
	game:GetService("InsertService"):SetCollectionUrl(BaseURL .. "/Game/Tools/InsertAsset.ashx?sid=%d")
	game:GetService("InsertService"):SetAssetUrl(BaseURL .. "/Asset/?id=%d")
	game:GetService("InsertService"):SetAssetVersionUrl(BaseURL .. "/Asset/?assetversionid=%d")

    game:GetService("Players"):SetSaveDataUrl(BaseURL .. "/persistence/legacy/save?userId=%d")
    game:GetService("Players"):SetLoadDataUrl(BaseURL .. "/persistence/legacy/load?userId=%d")

    game:GetService("FriendService"):SetMakeFriendUrl(BaseURL .. "/Friend/CreateFriend?firstUserId=%d&secondUserId=%d")
    game:GetService("FriendService"):SetBreakFriendUrl(BaseURL .. "/Friend/BreakFriend?firstUserId=%d&secondUserId=%d")
    game:GetService("FriendService"):SetGetFriendsUrl(BaseURL .. "/Friend/AreFriends?userId=%d")
    game:GetService("FriendService"):SetCreateFriendRequestUrl(BaseURL .. "/Friend/CreateFriendRequest?requesterUserId=%d&requestedUserId=%d")
    game:GetService("FriendService"):SetDeleteFriendRequestUrl(BaseURL .. "/Friend/DeleteFriendRequest?requesterUserId=%d&requestedUserId=%d")

	--pcall(function() loadfile(BaseURL .. "/Game/LoadPlaceInfo.ashx?PlaceId=" .. PlaceId)() end) idk what this is suppose to return
end

pcall(function() 
    game:GetService("NetworkServer"):SetIsPlayerAuthenticationRequired(false) 
end)
settings().Diagnostics.LuaRamLimit = 0

local StartTime = tick()
local StoppingServer = false
local function ReportServerPlayers(IgnoreThisPlayer)
    --if StoppingServer then return end
    local success, message = pcall(function()
        local PlayerList = {}
        for _, player in pairs(Players:GetChildren()) do
            if player:IsA("Player") and player ~= IgnoreThisPlayer then
                table.insert(PlayerList, {
                    ["UserId"] = player.UserId,
                    ["Name"] = player.Name
                })
            end
        end
        local MessagePayload = HttpService:JSONEncode({
            ["AuthToken"] = AuthToken,
            ["JobId"] = game.JobId,
            ["Players"] = PlayerList
        })
        local ResponseData = game:HttpPost(BaseURL.."/internal/gameserver/reportplayers", MessagePayload, true, "application/json")
        local ResponseJSON = HttpService:JSONDecode(ResponseData)
        for _, player in pairs(ResponseJSON["bad"]) do -- This is a list of players that need to be kicked from the server
            local TargetPlayer = Players:GetPlayerByUserId(player)
            if TargetPlayer ~= nil then
                TargetPlayer:Kick("There was an issue authenticating you, please contact support.")
                TargetPlayer:Destroy()
            end
        end

    end)
end

local function ReportServerStats()
    if StoppingServer then return end
    local success, message = pcall(function()
        local MessagePayload = HttpService:JSONEncode({
            ["AuthToken"] = AuthToken,
            ["JobId"] = game.JobId,
            ["PlaceId"] = PlaceId,
            ["ServerAliveTime"] = (tick() - StartTime) + 1
        })
        game:HttpPost(BaseURL.."/internal/gameserver/reportstats", MessagePayload, false, "application/json")
    end)
end

local function ReportServerShutdown()
    local success, message = pcall(function()
        local MessagePayload = HttpService:JSONEncode({
            ["AuthToken"] = AuthToken,
            ["JobId"] = game.JobId,
            ["PlaceId"] = PlaceId,
            ["ServerAliveTime"] = tick() - StartTime
        })
        game:HttpPost(BaseURL.."/internal/gameserver/reportshutdown", MessagePayload, false, "application/json")
    end)
end

local function ShutdownServer()
    StoppingServer = true
    ReportServerShutdown()
    ScriptContext.ScriptsDisabled = true
    game:HttpPost("http://127.0.0.1:3000/CloseJob?RCCReturnAuth="..AuthToken, HttpService:JSONEncode({
        ["jobid"] = game.JobId
    }), false, "application/json")
end

if PlaceId ~= nil and BaseURL ~= nil then
    wait()
    local success, message = pcall(function()
        game:Load(BaseURL.."/asset/?id="..tostring(PlaceId).."&access="..DownloadAuthorizationToken)
    end)
    if not success then
        -- Report error
        local MessagePayload = HttpService:JSONEncode({
            ["AuthToken"] = AuthToken,
            ["JobId"] = game.JobId,
            ["PlaceId"] = PlaceId,
            ["Error"] = message
        })
        game:HttpPost(BaseURL.."/internal/gameserver/reportfailure", MessagePayload, false, "application/json")
        -- Lets start the server but with an empty place and a error message
        local NewMessage = Instance.new("Message", workspace)
        NewMessage.Text = "There was an error loading this place file, Error Message: "..message..", PlaceId: "..tostring(PlaceId)..", JobId: "..tostring(game.JobId)
    end
end

NetworkServer:Start(Port)
ScriptContext:SetTimeout(10)
ScriptContext.ScriptsDisabled = false

local TotalPlayersJoined = 0

Players.PlayerAdded:Connect(function(player)
    ReportServerPlayers()
    TotalPlayersJoined = TotalPlayersJoined + 1
    player.DataComplexityLimit = 1024 * 1024 * 1
    player:LoadData()

    coroutine.wrap(function()
        while true do
            wait(120)
            if StoppingServer then break end
            if player.Parent == nil then break end
            player:SaveData()
        end
    end)()
end)
Players.PlayerRemoving:Connect(function(player)
    ReportServerPlayers(player)
    player:SaveData()
    local PlayerCount = #Players:GetPlayers()
    if PlayerCount == 0 then
        wait(10) -- Wait 10 seconds to see if anyone rejoins
        PlayerCount = #Players:GetPlayers()
        if PlayerCount == 0 then
            ShutdownServer()
        end
    end
end)

game:GetService("RunService"):Run()
ReportServerStats()

coroutine.wrap(function()
    while true do
        wait(20)
        if StoppingServer then break end
        ReportServerStats()
        ReportServerPlayers()
    end
end)()

coroutine.wrap(function()
    wait(120) -- Wait 2 minutes to check if anyone has joined
    if TotalPlayersJoined == 0 then
        warn("Stopping server, no players joined past 2 minutes.")
        ShutdownServer()
    end
end)()
