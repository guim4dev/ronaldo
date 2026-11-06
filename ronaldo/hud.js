ObjC.import("Cocoa");
ObjC.bindFunction("getppid", ["int", []]);

var ppid = $.getppid();
var argv = $.NSProcessInfo.processInfo.arguments;
var path = ObjC.unwrap(argv.objectAtIndex(4));
var app = $.NSApplication.sharedApplication;
app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);

var screen = $.NSScreen.mainScreen;
var visibleFrame = screen.visibleFrame;
var width = 380;
var padding = 18;
var style = $.NSWindowStyleMaskBorderless | $.NSWindowStyleMaskNonactivatingPanel;
var panel = $.NSPanel.alloc.initWithContentRectStyleMaskBackingDefer(
    $.NSMakeRect(visibleFrame.origin.x + visibleFrame.size.width - width - 20,
        visibleFrame.origin.y + visibleFrame.size.height - 88, width, 68),
    style, $.NSBackingStoreBuffered, false
);
panel.setLevel($.NSStatusWindowLevel);
panel.setCollectionBehavior(
    $.NSWindowCollectionBehaviorCanJoinAllSpaces |
    $.NSWindowCollectionBehaviorFullScreenAuxiliary |
    $.NSWindowCollectionBehaviorStationary
);
panel.setIgnoresMouseEvents(true);
panel.setOpaque(false);
panel.setBackgroundColor($.NSColor.clearColor);

var view = $.NSView.alloc.initWithFrame($.NSMakeRect(0, 0, width, 68));
view.setWantsLayer(true);
view.layer.setCornerRadius(14);
view.layer.setMasksToBounds(true);

var colors = {
    ok: $.NSColor.colorWithCalibratedRedGreenBlueAlpha(0.06, 0.24, 0.18, 0.94),
    err: $.NSColor.colorWithCalibratedRedGreenBlueAlpha(0.32, 0.08, 0.08, 0.95),
    warn: $.NSColor.colorWithCalibratedRedGreenBlueAlpha(0.32, 0.22, 0.05, 0.95),
    info: $.NSColor.colorWithCalibratedRedGreenBlueAlpha(0.10, 0.11, 0.14, 0.94)
};
view.layer.setBackgroundColor(colors.info.CGColor);
panel.setContentView(view);

var titleField = $.NSTextField.alloc.initWithFrame($.NSMakeRect(padding, 32, width - 2 * padding, 20));
var bodyField = $.NSTextField.alloc.initWithFrame($.NSMakeRect(padding, padding, width - 2 * padding, 18));
[titleField, bodyField].forEach(function (field) {
    field.setBezeled(false);
    field.setDrawsBackground(false);
    field.setEditable(false);
    field.setSelectable(false);
    field.setTextColor($.NSColor.whiteColor);
    view.addSubview(field);
});
titleField.setFont($.NSFont.boldSystemFontOfSize(15));
bodyField.setFont($.NSFont.systemFontOfSize(13));
bodyField.setUsesSingleLineMode(false);
bodyField.cell.setWraps(true);
bodyField.cell.setScrollable(false);
panel.orderOut(null);

var raw = "";
var hide = 0;

function showState(state) {
    var lines = String(state.body || "").split("\n");
    var visibleLines = [];
    lines.forEach(function (line) {
        while (line.length > 48) {
            visibleLines.push(line.slice(0, 48));
            line = line.slice(48);
        }
        visibleLines.push(line);
    });
    if (visibleLines.length > 8) {
        visibleLines = visibleLines.slice(0, 8);
        visibleLines[7] = visibleLines[7].slice(0, 45) + "…";
    }

    var body = visibleLines.join("\n");
    var bodyHeight = Math.max(1, visibleLines.length) * 18;
    var height = Math.max(68, 60 + bodyHeight);
    view.setFrame($.NSMakeRect(0, 0, width, height));
    panel.setFrameDisplay($.NSMakeRect(
        visibleFrame.origin.x + visibleFrame.size.width - width - 20,
        visibleFrame.origin.y + visibleFrame.size.height - height - 20,
        width, height
    ), false);
    titleField.setFrame($.NSMakeRect(padding, height - padding - 20, width - 2 * padding, 20));
    bodyField.setFrame($.NSMakeRect(padding, padding, width - 2 * padding, bodyHeight + 4));
    titleField.setStringValue(String(state.title || ""));
    bodyField.setStringValue(body);
    view.layer.setBackgroundColor((colors[state.kind] || colors.info).CGColor);
    panel.performSelector($.NSSelectorFromString("orderFrontRegardless"));
    $.NSFileHandle.fileHandleWithStandardError.writeData(
        $("hud mostrado " + state.id + "\n").dataUsingEncoding($.NSUTF8StringEncoding)
    );
    hide = Date.now() + Math.max(0.1, Number(state.seconds) || 6) * 1000;
}

while ($.getppid() === ppid) {
    $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(0.1));
    var stateFile = $.NSString.stringWithContentsOfFileEncodingError(
        $(path), $.NSUTF8StringEncoding, null
    );
    var text = stateFile.isNil() ? "" : ObjC.unwrap(stateFile);
    if (text && text !== raw) {
        raw = text;
        var state;
        try {
            state = JSON.parse(text);
        } catch (error) {
            // Ignore invalid or partially written JSON and retry on the next update.
            state = null;
        }
        if (state) {
            try {
                showState(state);
            } catch (error) {
                $.NSFileHandle.fileHandleWithStandardError.writeData(
                    $("hud erro: " + error + "\n").dataUsingEncoding($.NSUTF8StringEncoding)
                );
            }
        }
    }
    if (hide && Date.now() >= hide) {
        panel.orderOut(null);
        hide = 0;
    }
}
panel.orderOut(null);
