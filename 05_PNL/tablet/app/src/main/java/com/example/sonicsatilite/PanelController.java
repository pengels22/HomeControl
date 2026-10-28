package com.example.sonicsatilite;

import android.os.Handler;
import android.os.Looper;
import android.os.Build;
import android.provider.Settings;
import android.graphics.drawable.Drawable;
import android.graphics.PorterDuff;
import android.util.Log;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.SeekBar;
import android.widget.Spinner;
import android.widget.Switch;
import android.widget.TextView;
import android.graphics.Typeface;
import android.text.SpannableString;
import android.text.Spanned;
import android.text.TextPaint;
import android.text.style.MetricAffectingSpan;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import com.mikepenz.iconics.typeface.IIcon;
import com.mikepenz.iconics.typeface.library.community.material.CommunityMaterial;
import com.mikepenz.iconics.typeface.library.phosphor.Phosphor;

/** Server-authoritative dashboard state and actions. Never shares the audio executor. */
final class PanelController {
    private static final long REFRESH_MS = 2000L;
    private static final String GLOW = "light.living_room_glow_all";
    private static final String LAMP = "switch.lamp_switch";
    private static final String OFFICE = "switch.office_lights_switch";
    private static final String FAN = "switch.bedroom_camera_power";
    private static final String CLIMATE = "climate.nest_thermostat";
    private static final String INSIDE_TEMP = "sensor.average_temp";
    private static final String INSIDE_HUMIDITY = "sensor.average_humidity";
    private static final String OUTSIDE_TEMP = "sensor.outside_temp_temperature";
    private static final String OUTSIDE_HUMIDITY = "sensor.outside_temp_humidity";
    private static final List<String> LIGHTING_ORDER = Arrays.asList(GLOW, LAMP, OFFICE, FAN);
    private static final List<String> OFFICE_LIGHTING_ORDER = Arrays.asList(
            "switch.office_lights_switch_2",
            "switch.printer_lights_switch", "switch.workbench_switch",
            "light.office_desk_lights", "light.office_laser_fan");
    private static final List<String> BEDROOM_LIGHTING_ORDER = Arrays.asList(
            "light.bedroom_lamp_light", "light.headboard_white_light",
            "switch.barbecue_lights_switch", "switch.bedroom_fan_switch",
            "switch.bedroom_light", "switch.bedroom_vines_switch");
    private static final List<String> BEDROOM_AUTOMATION_ORDER = Arrays.asList(
            "automation.full_bed", "automation.good_morning1");
    private static final String BEDROOM_CURTAIN = "select.bedroom_curtain_bedroom_curtain_position_preset";
    private static final int SOURCE_SLOT_COUNT = 7;

    private final MainActivity activity;
    private final SonicApi api;
    private final ExecutorService executor;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable poll = new Runnable() { @Override public void run() { refresh(); } };
    private final Map<String, JSONObject> controls = new HashMap<>();
    private final Map<String, JSONObject> states = new HashMap<>();
    private boolean visible;
    private boolean pollInFlight;
    private boolean actionInFlight;
    private boolean configLoaded;
    private boolean suppressSlider;
    private boolean suppressClimateMode;
    private boolean sourceStatusOwnedByAction;
    private String pendingActionId;
    private JSONObject climateControl;
    private JSONObject mediaControl;
    private JSONArray apiConfigSources;
    private final Typeface mdiFont;
    private final Typeface phosphorFont;

    PanelController(MainActivity activity, SonicApi api, ExecutorService executor) {
        this.activity = activity;
        this.api = api;
        this.executor = executor;
        mdiFont = loadFont("community_material_design_icons_font_v7_0_96", "com.mikepenz.iconics.typeface.library.community");
        phosphorFont = loadFont("phosphor_v1_0_0", "com.mikepenz.iconics.typeface.library.phosphor");
        Log.i("PanelController", "ICON_FONTS mdi=" + (mdiFont != null) + " phosphor=" + (phosphorFont != null));
        wireControls();
        configureOfficeLayout();
        configureBedroomLayout();
        standardizeCardTitles();
    }

    private boolean isOfficeTablet() {
        return "KFKAWI".equalsIgnoreCase(Build.MODEL) || "karnak".equalsIgnoreCase(Build.DEVICE);
    }

    private boolean isBedroomTablet() {
        return "G0W0MB068265F06A".equals(Build.SERIAL);
    }

    private List<String> lightingOrder() {
        return isOfficeTablet() ? OFFICE_LIGHTING_ORDER : isBedroomTablet() ? BEDROOM_LIGHTING_ORDER : LIGHTING_ORDER;
    }

    private void configureOfficeLayout() {
        if (!isOfficeTablet() && !isBedroomTablet()) return;
        View media = activity.findViewById(R.id.media_card);
        if (media != null) media.setVisibility(View.GONE);
        View sources = activity.findViewById(R.id.sources_card);
        if (sources != null) sources.setVisibility(View.GONE);
        View bottom = activity.findViewById(R.id.dashboard_bottom_cards);
        if (bottom != null && isOfficeTablet()) bottom.setVisibility(View.GONE);
        TextView header = activity.findViewById(R.id.homecontrol_header);
        if (header != null) header.setText(isOfficeTablet() ? "Office" : "Bedroom");
        Log.i("PanelController", (isOfficeTablet() ? "OFFICE" : "BEDROOM") + "_LAYOUT media and source cards hidden");
    }

    private void configureBedroomLayout() {
        if (!isBedroomTablet()) return;
        LinearLayout top = activity.findViewById(R.id.dashboard_top_cards);
        LinearLayout bottom = activity.findViewById(R.id.dashboard_bottom_cards);
        if (top != null) {
            top.setOrientation(LinearLayout.VERTICAL);
            for (int i = 0; i < top.getChildCount(); i++) {
                View child = top.getChildAt(i);
                LinearLayout.LayoutParams lp = (LinearLayout.LayoutParams) child.getLayoutParams();
                lp.width = LinearLayout.LayoutParams.MATCH_PARENT;
                lp.height = 0;
                lp.weight = 1f;
                child.setLayoutParams(lp);
            }
            View climate = activity.findViewById(R.id.climate_card);
            View climateBody = activity.findViewById(R.id.climate_body);
            if (climate != null && climateBody != null) {
                LinearLayout.LayoutParams climateParams = (LinearLayout.LayoutParams) climate.getLayoutParams();
                climateParams.height = LinearLayout.LayoutParams.WRAP_CONTENT;
                climateParams.weight = 0f;
                climate.setLayoutParams(climateParams);
                LinearLayout.LayoutParams bodyParams = (LinearLayout.LayoutParams) climateBody.getLayoutParams();
                bodyParams.height = LinearLayout.LayoutParams.WRAP_CONTENT;
                bodyParams.weight = 0f;
                climateBody.setLayoutParams(bodyParams);
            }
        }
        if (bottom != null) bottom.setVisibility(View.GONE);
        View curtain = activity.findViewById(R.id.curtain_card);
        if (curtain != null) {
            curtain.setVisibility(View.VISIBLE);
            LinearLayout.LayoutParams curtainParams = (LinearLayout.LayoutParams) curtain.getLayoutParams();
            curtainParams.width = LinearLayout.LayoutParams.MATCH_PARENT;
            curtainParams.height = LinearLayout.LayoutParams.WRAP_CONTENT;
            curtainParams.weight = 0f;
            curtain.setLayoutParams(curtainParams);
        }
        if (bottom != null) {
            LinearLayout.LayoutParams bottomParams = (LinearLayout.LayoutParams) bottom.getLayoutParams();
            bottomParams.height = LinearLayout.LayoutParams.WRAP_CONTENT;
            bottomParams.weight = 0f;
            bottom.setLayoutParams(bottomParams);
            bottom.setVisibility(View.VISIBLE);
        }
        Log.i("PanelController", "BEDROOM_LAYOUT cards stacked vertically");
    }

    void start() { visible = true; handler.removeCallbacks(poll); refresh(); }
    void stop() { visible = false; handler.removeCallbacks(poll); }
    void refreshNow() { if (visible) refresh(); }

    private void standardizeCardTitles() {
        int[] cards = {R.id.lights_card, R.id.climate_card, R.id.media_card, R.id.sources_card, R.id.curtain_card};
        for (int id : cards) {
            TextView title = firstTextView(activity.findViewById(id));
            if (title != null) title.setTextSize(14);
            if (id == R.id.lights_card && title != null) {
                title.setText("Lights"); title.setCompoundDrawablesWithIntrinsicBounds(icon(R.drawable.ic_light_bulb, 0xffffe37a), null, null, null);
                title.setCompoundDrawablePadding(dp(6));
            } else if (id == R.id.sources_card && title != null) {
                title.setText("Media Source"); title.setCompoundDrawablesWithIntrinsicBounds(icon(R.drawable.ic_source_tv, 0xfff5fbff), null, null, null);
                title.setCompoundDrawablePadding(dp(6));
            }
        }
    }

    private Drawable icon(int resource, int color) {
        Drawable drawable = activity.getResources().getDrawable(resource);
        drawable.setColorFilter(new android.graphics.PorterDuffColorFilter(color, android.graphics.PorterDuff.Mode.SRC_IN));
        return drawable;
    }

    private Typeface loadFont(String name, String packageName) {
        int id = activity.getResources().getIdentifier(name, "font", activity.getPackageName());
        if (id == 0) id = activity.getResources().getIdentifier(name, "font", packageName);
        return id == 0 ? null : androidx.core.content.res.ResourcesCompat.getFont(activity, id);
    }

    private void setFontIcon(TextView view, Typeface typeface, IIcon glyph) {
        if (typeface == null || glyph == null) return;
        view.setTypeface(typeface); view.setText(String.valueOf(glyph.getCharacter()));
    }

    private CharSequence sourceLabel(IIcon glyph, String label) {
        if (phosphorFont == null || glyph == null) return label;
        SpannableString text = new SpannableString(String.valueOf(glyph.getCharacter()) + "\n" + label);
        text.setSpan(new FontSpan(phosphorFont), 0, 1, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        return text;
    }

    private static final class FontSpan extends MetricAffectingSpan {
        private final Typeface typeface;
        FontSpan(Typeface typeface) { this.typeface = typeface; }
        @Override public void updateDrawState(TextPaint paint) { paint.setTypeface(typeface); }
        @Override public void updateMeasureState(TextPaint paint) { paint.setTypeface(typeface); }
    }

    private TextView firstTextView(View view) {
        if (view instanceof TextView) return (TextView) view;
        if (view instanceof android.view.ViewGroup) {
            android.view.ViewGroup group = (android.view.ViewGroup) view;
            for (int i = 0; i < group.getChildCount(); i++) {
                TextView found = firstTextView(group.getChildAt(i));
                if (found != null) return found;
            }
        }
        return null;
    }

    private void wireControls() {
        // The old aggregate switch is deliberately inert. Visible rows are bound
        // to their exact configured entity IDs in renderLights().
        activity.findViewById(R.id.lights_toggle).setVisibility(View.GONE);
        activity.findViewById(R.id.lights_all_off).setOnClickListener(v -> allOff());
        styleControlButton(R.id.lights_all_off);
        View climateDown = activity.findViewById(R.id.climate_down);
        View climateUp = activity.findViewById(R.id.climate_up);
        if (climateDown instanceof Button) ((Button) climateDown).setBackgroundTintList(null);
        if (climateUp instanceof Button) ((Button) climateUp).setBackgroundTintList(null);
        styleControlButton(R.id.media_previous);
        styleControlButton(R.id.media_play_pause);
        styleControlButton(R.id.media_next);
        SeekBar brightness = activity.findViewById(R.id.lights_brightness);
        brightness.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            public void onProgressChanged(SeekBar b, int p, boolean fromUser) {
                ((TextView) activity.findViewById(R.id.lights_brightness_text)).setText("Brightness: " + p + "%");
            }
            public void onStartTrackingTouch(SeekBar b) { }
            public void onStopTrackingTouch(SeekBar b) {
                if (!suppressSlider) action(GLOW, "set_brightness", value("brightness_pct", b.getProgress()));
            }
        });
        activity.findViewById(R.id.climate_down).setOnClickListener(v -> changeTemperature(-1));
        activity.findViewById(R.id.climate_up).setOnClickListener(v -> changeTemperature(1));
        Spinner mode = activity.findViewById(R.id.climate_mode);
        mode.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener() {
            public void onItemSelected(android.widget.AdapterView<?> parent, View view, int position, long id) {
                if (suppressClimateMode || climateControl == null || position < 0) return;
                String selected = String.valueOf(parent.getItemAtPosition(position));
                JSONObject live = states.get(CLIMATE);
                // Spinner callbacks also run for setAdapter()/setSelection().
                // A mode equal to HA's current state is never a user command.
                if (live != null && selected.equals(live.optString("state"))) {
                    Log.i("PanelController", "IGNORED_PROGRAMMATIC climate mode=" + selected);
                    return;
                }
                action(CLIMATE, "set_hvac_mode", value("hvac_mode", selected));
            }
            public void onNothingSelected(android.widget.AdapterView<?> parent) { }
        });
        activity.findViewById(R.id.media_previous).setOnClickListener(v -> action(mediaId(), "media_previous_track", null));
        activity.findViewById(R.id.media_play_pause).setOnClickListener(v -> action(mediaId(), "media_play_pause", null));
        activity.findViewById(R.id.media_next).setOnClickListener(v -> action(mediaId(), "media_next_track", null));
        SeekBar volume = activity.findViewById(R.id.media_volume);
        volume.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            public void onProgressChanged(SeekBar b, int p, boolean fromUser) {
                ((TextView) activity.findViewById(R.id.media_volume_text)).setText("Volume: " + p + "%");
            }
            public void onStartTrackingTouch(SeekBar b) { }
            public void onStopTrackingTouch(SeekBar b) {
                if (!suppressSlider) action(mediaId(), "volume_set", value("volume_level", b.getProgress() / 100.0));
            }
        });
    }

    private JSONObject value(String key, Object value) {
        JSONObject o = new JSONObject();
        try { o.put(key, value); } catch (Exception ignored) { }
        return o;
    }

    private void refresh() {
        if (!visible || pollInFlight) return;
        pollInFlight = true;
        executor.execute(() -> {
            String error = null;
            try {
                if (!configLoaded) { parseConfig(api.panelConfig()); configLoaded = true; }
                parseStates(api.panelStates());
            } catch (Exception e) { error = safePanelError(e); }
            final String result = error;
            activity.runOnUiThread(() -> {
                pollInFlight = false;
                if (result == null) render(); else showUnavailable(result);
                if (visible) { handler.removeCallbacks(poll); handler.postDelayed(poll, REFRESH_MS); }
            });
        });
    }

    private void parseConfig(JSONObject config) throws Exception {
        controls.clear(); climateControl = null; mediaControl = null;
        apiConfigSources = config.optJSONArray("media_sources");
        JSONArray array = config.optJSONArray("controls");
        if (array == null) throw new Exception("Panel configuration unavailable");
        for (int i = 0; i < array.length(); i++) {
            JSONObject c = array.optJSONObject(i); if (c == null) continue;
            String id = c.optString("entity_id", "");
            String type = c.optString("type", "");
            if (!validEntity(id)) continue;
            // Domains are never inferred from a different controller category.
            if ("climate".equals(type) && CLIMATE.equals(id)) climateControl = c;
            if ("media_player".equals(type) && id.startsWith("media_player.")) mediaControl = c;
            if (lightingOrder().contains(id) || BEDROOM_AUTOMATION_ORDER.contains(id) || BEDROOM_CURTAIN.equals(id) || CLIMATE.equals(id)
                    || INSIDE_TEMP.equals(id) || INSIDE_HUMIDITY.equals(id) || OUTSIDE_TEMP.equals(id) || OUTSIDE_HUMIDITY.equals(id)
                    || ("media_player".equals(type) && id.startsWith("media_player."))) controls.put(id, c);
        }
        Log.i("PanelController", "CONFIG controls=" + controls.keySet()
                + " climate=" + (climateControl == null ? "none" : CLIMATE)
                + " media=" + mediaId() + " sourceMappings="
                + (apiConfigSources == null ? 0 : apiConfigSources.length()));
    }

    private void parseStates(JSONObject snapshot) throws Exception {
        states.clear(); JSONArray array = snapshot.optJSONArray("states");
        if (array == null) throw new Exception("Invalid panel state snapshot");
        for (int i = 0; i < array.length(); i++) {
            JSONObject s = array.optJSONObject(i);
            if (s != null && controls.containsKey(s.optString("entity_id"))) states.put(s.optString("entity_id"), s);
        }
        Log.i("PanelController", "POLL states=" + states.keySet()
                + " climate=" + (states.containsKey(CLIMATE) ? states.get(CLIMATE).optString("state") : "missing"));
    }

    private void render() { renderLights(); renderBedroomCurtain(); renderClimate(); renderMedia(); renderSources(); }

    private void renderLights() {
        if (isBedroomTablet()) {
            renderBedroomLights();
            return;
        }
        if (isOfficeTablet()) {
            renderOfficeLights();
            return;
        }
        TextView label = activity.findViewById(R.id.lights_label);
        TextView state = activity.findViewById(R.id.lights_state);
        SeekBar bar = activity.findViewById(R.id.lights_brightness);
        Button off = activity.findViewById(R.id.lights_all_off);
        LinearLayout rows = activity.findViewById(R.id.lights_controls);
        rows.removeAllViews();
        int brightness = -1; boolean glowAvailable = false;
        List<String> lighting = lightingOrder();
        for (String id : lighting) {
            JSONObject c = controls.get(id); if (c == null) continue;
            JSONObject s = states.get(id);
            boolean available = s != null && s.optBoolean("available", !"unavailable".equals(s.optString("state")));
            LinearLayout row = new LinearLayout(activity);
            row.setGravity(android.view.Gravity.CENTER_VERTICAL);
            row.setOrientation(LinearLayout.HORIZONTAL);
            TextView icon = new TextView(activity);
            int lightIcon = GLOW.equals(id) ? R.drawable.ic_light_bulb : LAMP.equals(id) ? R.drawable.ic_light_lamp : OFFICE.equals(id) ? R.drawable.ic_light_switch : R.drawable.ic_light_fan;
            icon.setCompoundDrawablesWithIntrinsicBounds(null, icon(lightIcon, GLOW.equals(id) ? 0xffffe37a : 0xffeaf4fb), null, null);
            icon.setGravity(android.view.Gravity.CENTER);
            boolean largeControls = isOfficeTablet() || isLivingRoomTablet();
            row.addView(icon, new LinearLayout.LayoutParams(dp(largeControls ? 40 : 28), dp(largeControls ? 44 : 32)));
            TextView name = new TextView(activity);
            name.setText(lightLabel(id, c.optString("label", id))); name.setTextColor(0xfff4fbff); name.setTextSize(largeControls ? 15 : 13); name.setGravity(android.view.Gravity.CENTER_VERTICAL);
            row.addView(name, new LinearLayout.LayoutParams(0, dp(largeControls ? 44 : 32), 1f));
            final String entity = id;
            if (GLOW.equals(id) && available) {
                JSONObject a = s.optJSONObject("attributes");
                if (a != null && a.has("brightness") && !a.isNull("brightness")) brightness = Math.round((float) a.optInt("brightness") * 100f / 255f);
                TextView pct = new TextView(activity); pct.setText(brightness >= 0 ? brightness + "%" : "—"); pct.setTextColor(0xffdcecf5); pct.setTextSize(11); pct.setGravity(android.view.Gravity.CENTER);
                row.addView(pct, new LinearLayout.LayoutParams(dp(isLivingRoomTablet() ? 42 : 35), dp(largeControls ? 44 : 32)));
                SeekBar inline = new SeekBar(activity); inline.setMax(100); inline.setProgress(Math.max(0, brightness)); inline.setEnabled(supports(c, "set_brightness"));
                final TextView inlinePct = pct;
                inline.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
                    public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) { if (fromUser) inlinePct.setText(progress + "%"); }
                    public void onStartTrackingTouch(SeekBar seekBar) { }
                    public void onStopTrackingTouch(SeekBar seekBar) { action(entity, "set_brightness", value("brightness_pct", seekBar.getProgress())); }
                });
                row.addView(inline, new LinearLayout.LayoutParams(dp(isLivingRoomTablet() ? 128 : 78), dp(largeControls ? 44 : 32)));
            }
            Switch toggle = new Switch(activity); toggle.setText(""); toggle.setMinWidth(largeControls ? dp(64) : 48); toggle.setMinHeight(largeControls ? dp(44) : 30); toggle.setMinimumHeight(largeControls ? dp(44) : 30);
            if (isOfficeTablet()) { toggle.setScaleX(1.15f); toggle.setScaleY(1.15f); }
            toggle.setEnabled(available && (supports(c, "turn_on") || supports(c, "turn_off")));
            toggle.setChecked(available && "on".equals(s.optString("state")));
            toggle.setOnClickListener(v -> {
                if (isLivingRoomTablet()) styleLivingRoomLight(toggle, toggle.isChecked());
                action(entity, toggle.isChecked() ? "turn_on" : "turn_off", null);
            });
            row.addView(toggle, new LinearLayout.LayoutParams(dp(isOfficeTablet() ? 78 : isLivingRoomTablet() ? 64 : 48), dp(isOfficeTablet() ? 52 : isLivingRoomTablet() ? 44 : 32)));
            if (isLivingRoomTablet()) styleLivingRoomLight(row, name,
                    toggle, "on".equals(s == null ? "" : s.optString("state")));
            rows.addView(row, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(isOfficeTablet() ? 58 : isLivingRoomTablet() ? 48 : 34)));
            if (rows.getChildCount() < lighting.size()) { View divider = new View(activity); divider.setBackgroundColor(0x335C707A); rows.addView(divider, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 1)); }
            if (GLOW.equals(id) && available) {
                glowAvailable = true; JSONObject a = s.optJSONObject("attributes");
                if (a != null && a.has("brightness") && !a.isNull("brightness")) brightness = Math.round((float) a.optInt("brightness") * 100f / 255f);
            }
        }
        label.setText(isOfficeTablet() ? "Office" : isBedroomTablet() ? "Bedroom" : "Living Room");
        off.setEnabled(hasConfiguredLightingExceptFan());
        bar.setEnabled(glowAvailable && supports(controls.get(GLOW), "set_brightness"));
        if (brightness >= 0) { suppressSlider = true; bar.setProgress(brightness); suppressSlider = false; }
        ((TextView) activity.findViewById(R.id.lights_brightness_text)).setText(brightness >= 0 ? "Brightness: " + brightness + "%" : "Brightness: unsupported");
        state.setText(states.size() < controls.size() ? "Some entities unavailable" : "Live Home Assistant state");
    }

    private void styleLivingRoomLight(LinearLayout row, TextView name, Switch toggle, boolean on) {
        row.setBackgroundColor(0x00000000);
        row.setPadding(0, 0, 0, 0);
        name.setTextColor(0xfff4fbff);
        styleLivingRoomLight(toggle, on);
    }

    private void styleLivingRoomLight(Switch toggle, boolean on) {
        toggle.setBackgroundColor(0x00000000);
        toggle.setPadding(dp(4), 0, dp(4), 0);
        Drawable thumb = toggle.getThumbDrawable();
        if (thumb != null) {
            thumb = thumb.mutate();
            thumb.setColorFilter(on ? 0xffffffff : 0xff68747b, PorterDuff.Mode.SRC_IN);
        }
        Drawable track = toggle.getTrackDrawable();
        if (track != null) {
            track = track.mutate();
            track.setColorFilter(on ? 0x80ffffff : 0x8068747b, PorterDuff.Mode.SRC_IN);
        }
    }

    private void renderBedroomLights() {
        TextView label = activity.findViewById(R.id.lights_label);
        TextView state = activity.findViewById(R.id.lights_state);
        LinearLayout rows = activity.findViewById(R.id.lights_controls);
        rows.removeAllViews();
        label.setText("Bedroom");
        List<String> entities = new ArrayList<>();
        entities.addAll(BEDROOM_LIGHTING_ORDER);
        entities.addAll(BEDROOM_AUTOMATION_ORDER);
        LinearLayout currentRow = null;
        for (int i = 0; i < entities.size(); i++) {
            if (i % 2 == 0) {
                currentRow = new LinearLayout(activity);
                currentRow.setOrientation(LinearLayout.HORIZONTAL);
                currentRow.setGravity(android.view.Gravity.CENTER);
                rows.addView(currentRow, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));
            }
            String id = entities.get(i);
            JSONObject c = controls.get(id), s = states.get(id);
            boolean available = s != null && s.optBoolean("available", !"unavailable".equals(s.optString("state")));
            boolean automation = id.startsWith("automation.");
            String labelText = bedroomLabel(id, c == null ? id : c.optString("label", id));
            Button button = new Button(activity);
            button.setText(iconLabel(bedroomIcon(id), labelText));
            button.setTextSize(14);
            button.setTextColor(0xfff5fbff);
            button.setGravity(android.view.Gravity.CENTER);
            button.setAllCaps(false);
            button.setPadding(dp(5), dp(5), dp(5), dp(5));
            button.setMinHeight(dp(82));
            button.setMinWidth(dp(100));
            button.setBackgroundResource(R.drawable.dashboard_control_button);
            button.setBackgroundTintList(null);
            String actionName = automation ? "trigger" : ("on".equals(s == null ? "" : s.optString("state")) ? "turn_off" : "turn_on");
            button.setEnabled(available && c != null && supports(c, actionName));
            final String entity = id;
            button.setOnClickListener(v -> action(entity, automation ? "trigger" : ("on".equals(states.get(entity).optString("state")) ? "turn_off" : "turn_on"), null));
            LinearLayout cell = new LinearLayout(activity);
            cell.setOrientation(LinearLayout.VERTICAL);
            cell.setGravity(android.view.Gravity.CENTER);
            cell.addView(button, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(82)));
            boolean dimmable = !automation && available && c != null && supports(c, "set_brightness");
            if (dimmable) {
                SeekBar brightness = new SeekBar(activity);
                brightness.setMax(100);
                JSONObject attrs = s.optJSONObject("attributes");
                int percent = attrs != null && attrs.has("brightness") ? Math.round(attrs.optInt("brightness") * 100f / 255f) : 100;
                brightness.setProgress(Math.max(0, percent));
                brightness.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
                    public void onProgressChanged(SeekBar bar, int progress, boolean fromUser) { }
                    public void onStartTrackingTouch(SeekBar bar) { }
                    public void onStopTrackingTouch(SeekBar bar) { action(entity, "set_brightness", value("brightness_pct", bar.getProgress())); }
                });
                cell.addView(brightness, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(30)));
            } else {
                View spacer = new View(activity);
                cell.addView(spacer, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(30)));
            }
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, 1f);
            lp.setMargins(dp(5), dp(5), dp(5), dp(5));
            currentRow.addView(cell, lp);
        }
        state.setText("Live Home Assistant state");
    }

    private void renderBedroomCurtain() {
        if (!isBedroomTablet()) return;
        LinearLayout rows = activity.findViewById(R.id.curtain_controls);
        TextView stateLabel = activity.findViewById(R.id.curtain_state);
        if (rows == null) return;
        rows.removeAllViews();
        JSONObject control = controls.get(BEDROOM_CURTAIN);
        JSONObject current = states.get(BEDROOM_CURTAIN);
        if (control == null || current == null) {
            if (stateLabel != null) stateLabel.setText("Curtain not configured");
            return;
        }
        JSONObject attributes = current.optJSONObject("attributes");
        JSONArray configuredOptions = attributes == null ? null : attributes.optJSONArray("options");
        List<String> options = new ArrayList<>();
        if (configuredOptions != null) {
            for (int i = 0; i < configuredOptions.length(); i++) {
                String option = configuredOptions.optString(i, "");
                if (!option.isEmpty()) options.add(option);
            }
        }
        if (options.isEmpty()) options.add("Closed");
        LinearLayout row = new LinearLayout(activity);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(android.view.Gravity.CENTER);
        rows.addView(row, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));
        String selected = current.optString("state", "");
        for (int i = 0; i < options.size(); i++) {
            String option = options.get(i);
            Button button = new Button(activity);
            button.setText(option.equals(selected) ? "✓ " + option : option);
            button.setTextSize(14);
            button.setTextColor(0xfff5fbff);
            button.setAllCaps(false);
            button.setGravity(android.view.Gravity.CENTER);
            button.setPadding(dp(5), dp(5), dp(5), dp(5));
            button.setMinHeight(0);
            button.setMinimumHeight(0);
            button.setBackgroundResource(R.drawable.dashboard_control_button);
            button.setBackgroundTintList(null);
            button.setEnabled(supports(control, "select_option"));
            final String selectedOption = option;
            button.setOnClickListener(v -> action(BEDROOM_CURTAIN, "select_option", value("option", selectedOption)));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, dp(86), 1f);
            lp.gravity = android.view.Gravity.CENTER_VERTICAL;
            lp.setMargins(dp(5), dp(5), dp(5), dp(5));
            row.addView(button, lp);
        }
        if (stateLabel != null) stateLabel.setText("Current: " + selected);
    }

    private void renderOfficeLights() {
        TextView label = activity.findViewById(R.id.lights_label);
        TextView state = activity.findViewById(R.id.lights_state);
        LinearLayout rows = activity.findViewById(R.id.lights_controls);
        rows.removeAllViews();
        label.setText("Office Lights");
        String[] entities = OFFICE_LIGHTING_ORDER.toArray(new String[0]);
        for (int i = 0; i < entities.length; i++) {
            if (i % 3 == 0) {
                LinearLayout row = new LinearLayout(activity);
                row.setOrientation(LinearLayout.HORIZONTAL);
                row.setGravity(android.view.Gravity.CENTER);
                rows.addView(row, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(92)));
            }
            String id = entities[i];
            JSONObject c = controls.get(id);
            JSONObject s = states.get(id);
            boolean available = s != null && s.optBoolean("available", !"unavailable".equals(s.optString("state")));
            Button button = new Button(activity);
            button.setText(lightLabel(id, c == null ? id : c.optString("label", id)));
            button.setTextSize(12);
            button.setTextColor(0xfff5fbff);
            button.setGravity(android.view.Gravity.CENTER);
            button.setAllCaps(false);
            button.setMinHeight(dp(82));
            button.setMinWidth(dp(82));
            button.setPadding(dp(4), dp(4), dp(4), dp(4));
            button.setBackgroundResource(R.drawable.dashboard_control_button);
            button.setBackgroundTintList(null);
            int iconResource = id.startsWith("light.office_laser") ? R.drawable.ic_light_fan
                    : id.startsWith("light.office_") ? R.drawable.ic_light_bulb
                    : id.contains("printer") ? R.drawable.ic_light_lamp
                    : R.drawable.ic_light_switch;
            button.setCompoundDrawablesWithIntrinsicBounds(null, icon(iconResource, 0xffffe37a), null, null);
            button.setCompoundDrawablePadding(dp(4));
            button.setEnabled(available && c != null && (supports(c, "turn_on") || supports(c, "turn_off")));
            final String entity = id;
            button.setOnClickListener(v -> action(entity, "on".equals(states.get(entity).optString("state")) ? "turn_off" : "turn_on", null));
            LinearLayout row = (LinearLayout) rows.getChildAt(rows.getChildCount() - 1);
            LinearLayout.LayoutParams buttonParams = new LinearLayout.LayoutParams(0, dp(82), 1f);
            buttonParams.setMargins(dp(3), dp(3), dp(3), dp(3));
            row.addView(button, buttonParams);
        }
        state.setText("Live Home Assistant state");
    }

    private int dp(int value) { return Math.round(value * activity.getResources().getDisplayMetrics().density); }

    private boolean isLivingRoomTablet() {
        String serial = Build.SERIAL;
        String androidId = Settings.Secure.getString(activity.getContentResolver(), Settings.Secure.ANDROID_ID);
        return "G0W0MB068265F04A".equals(serial) || "70071a26b3ce6ab1".equals(androidId);
    }

    private void renderClimate() {
        TextView current = activity.findViewById(R.id.climate_current), target = activity.findViewById(R.id.climate_target), status = activity.findViewById(R.id.climate_status);
        TextView environment = activity.findViewById(R.id.climate_environment);
        Spinner mode = activity.findViewById(R.id.climate_mode); JSONObject s = climateControl == null ? null : states.get(CLIMATE);
        boolean ok = climateControl != null && s != null && s.optBoolean("available", true);
        boolean tempControl = ok && supports(climateControl, "set_temperature");
        boolean modeControl = ok && supports(climateControl, "set_hvac_mode");
        activity.findViewById(R.id.climate_down).setEnabled(tempControl);
        activity.findViewById(R.id.climate_up).setEnabled(tempControl);
        mode.setEnabled(modeControl);
        LinearLayout modeButtons = activity.findViewById(R.id.climate_mode_buttons);
        modeButtons.removeAllViews();
        Log.i("PanelController", "CLIMATE configured=" + (climateControl != null)
                + " state=" + (s == null ? "missing" : s.optString("state"))
                + " tempControl=" + tempControl + " modeControl=" + modeControl);
        if (!ok) { current.setText("—"); target.setText("Target: —"); status.setText("Climate not configured"); mode.setAdapter(new ArrayAdapter<String>(activity, android.R.layout.simple_spinner_item, new String[0])); return; }
        environment.setText("Inside " + sensorReading(INSIDE_TEMP) + " • " + sensorReading(INSIDE_HUMIDITY)
                + "\nOutside " + sensorReading(OUTSIDE_TEMP) + " • " + sensorReading(OUTSIDE_HUMIDITY));
        JSONObject a = s.optJSONObject("attributes"); String unit = a == null ? "" : a.optString("temperature_unit", a.optString("unit_of_measurement", ""));
        String currentTemp = formatTemp(a == null ? null : a.opt("current_temperature"), unit);
        String targetTemp = formatTemp(a == null ? null : a.opt("temperature"), unit);
        String modeLabel = s.optString("state", "");
        String actionLabel = modeLabel.contains("cool") ? "Cooling to" : modeLabel.contains("heat") ? "Heating to" : "Target";
        current.setText(currentTemp); target.setText("Currently " + currentTemp + "\n" + actionLabel + " " + targetTemp);
        String hvacAction = a == null ? "" : a.optString("hvac_action", ""); status.setText(s.optString("state", "unknown") + (hvacAction.isEmpty() ? "" : " • " + hvacAction));
        List<String> modes = new ArrayList<>(); if (a != null) { JSONArray hvac = a.optJSONArray("hvac_modes"); if (hvac != null) for (int i = 0; i < hvac.length(); i++) modes.add(hvac.optString(i)); }
        List<String> visibleModes = Arrays.asList("heat", "cool", "heat_cool");
        for (String hvacMode : visibleModes) {
            if (!modes.contains(hvacMode)) continue;
            Button button = new Button(activity);
            IIcon modeGlyph = "heat".equals(hvacMode) ? CommunityMaterial.Icon2.cmd_fire : "cool".equals(hvacMode) ? CommunityMaterial.Icon3.cmd_snowflake : CommunityMaterial.Icon3.cmd_sun_snowflake;
            button.setText("");
            button.setContentDescription(hvacMode.replace('_', ' '));
            setFontIcon(button, mdiFont, modeGlyph);
            button.setTextSize(28);
            button.setTextColor("heat".equals(hvacMode) ? 0xffffd166 : 0xff82d7ff);
            button.setTextColor(0xfff5fbff);
            button.setBackgroundResource(R.drawable.climate_round_button);
            button.setBackgroundTintList(null);
            button.setEnabled(modeControl);
            if (hvacMode.equals(s.optString("state"))) {
                button.setTextColor(0xfff5fbff);
                button.setBackgroundResource(R.drawable.climate_active_button);
            }
            final String selectedMode = hvacMode;
            button.setOnClickListener(v -> {
                if (selectedMode.equals(states.get(CLIMATE).optString("state"))) {
                    Log.i("PanelController", "TOGGLE_CLIMATE_BUTTON current=" + selectedMode + " -> off");
                    action(CLIMATE, "set_hvac_mode", value("hvac_mode", "off"));
                    return;
                }
                action(CLIMATE, "set_hvac_mode", value("hvac_mode", selectedMode));
            });
            LinearLayout.LayoutParams modeParams = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, 1f);
            modeParams.setMargins(3, 0, 3, 0);
            modeButtons.addView(button, modeParams);
        }
        ArrayAdapter<String> adapter = new ArrayAdapter<>(activity, android.R.layout.simple_spinner_item, modes); adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        suppressClimateMode = true; mode.setAdapter(adapter); int selected = modes.indexOf(s.optString("state")); if (selected >= 0) mode.setSelection(selected); suppressClimateMode = false;
    }

    private String sensorReading(String entity) {
        JSONObject s = states.get(entity);
        if (s == null || !s.optBoolean("available", false)) return "—";
        JSONObject a = s.optJSONObject("attributes");
        String unit = a == null ? "" : a.optString("unit_of_measurement", "");
        return s.optString("state", "—") + (unit.isEmpty() ? "" : " " + unit);
    }

    private void renderMedia() {
        String id = mediaId(); JSONObject s = states.get(id); boolean ok = mediaControl != null && s != null && s.optBoolean("available", true);
        TextView title = activity.findViewById(R.id.media_title), detail = activity.findViewById(R.id.media_detail); JSONObject a = ok ? s.optJSONObject("attributes") : null;
        title.setText(ok ? (a == null ? "Now playing" : a.optString("media_title", "Now playing")) : "Media not configured");
        detail.setText(ok ? s.optString("state", "unknown") + " • " + (a == null ? "" : a.optString("media_artist", "")) : "Configure a media_player entity on Server1");
        int f = a == null ? 0 : a.optInt("supported_features", 0);
        setMedia(R.id.media_previous, ok && supports(mediaControl, "media_previous_track") && (f == 0 || (f & 16) != 0));
        setMedia(R.id.media_next, ok && supports(mediaControl, "media_next_track") && (f == 0 || (f & 32) != 0));
        setMedia(R.id.media_play_pause, ok && supports(mediaControl, "media_play_pause") && (f == 0 || (f & 1) != 0));
        SeekBar volume = activity.findViewById(R.id.media_volume); boolean volumeOk = ok && supports(mediaControl, "volume_set") && a != null && a.has("volume_level"); volume.setEnabled(volumeOk);
        if (volumeOk) { suppressSlider = true; volume.setProgress(Math.round((float) a.optDouble("volume_level") * 100)); suppressSlider = false; }
        ((TextView) activity.findViewById(R.id.media_volume_text)).setText(volumeOk ? "Volume: " + volume.getProgress() + "%" : "Volume: unsupported");
    }

    private void renderSources() {
        LinearLayout grid = activity.findViewById(R.id.source_grid); grid.removeAllViews(); boolean hasMapping = false;
        LinearLayout currentRow = null;
        for (int i = 0; i < SOURCE_SLOT_COUNT; i++) {
            if (i % 4 == 0) {
                currentRow = new LinearLayout(activity);
                currentRow.setOrientation(LinearLayout.HORIZONTAL);
                grid.addView(currentRow, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                        isLivingRoomTablet() ? 38 : 50));
            }
            JSONObject source = sourceAt(i); Button button = new Button(activity);
            String[] referenceLabels = {"Wii", "TV", "Xbox", "Cube", "PS2", "Music", "Pi"};
            String sourceLabel = referenceLabels[i];
            if (source != null) {
                String configuredLabel = source.optString("label", "").trim();
                String configuredSource = source.optString("source", "").trim();
                if (!configuredLabel.isEmpty()) sourceLabel = configuredLabel;
                else if (!configuredSource.isEmpty()) sourceLabel = configuredSource;
            }
            button.setText(isLivingRoomTablet() ? sourceLabel : sourceLabel(sourceGlyph(sourceLabel), sourceLabel));
            button.setTextColor(0xfff5fbff);
            button.setTextSize(12);
            button.setGravity(android.view.Gravity.CENTER);
            button.setBackgroundResource(R.drawable.dashboard_control_button);
            button.setBackgroundTintList(null);
            boolean configured = source != null && validMediaSource(source) && controls.containsKey(source.optString("entity_id")); button.setEnabled(configured); hasMapping |= configured;
            if (configured) { final JSONObject selected = source; button.setOnClickListener(v -> { setSourceStatus("Pending: " + selected.optString("label", "Source")); action(selected.optString("entity_id"), "select_media_source", value("source", selected.optString("source", ""))); }); }
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, isLivingRoomTablet() ? 36 : 48, 1f);
            lp.setMargins(2, 1, 2, 1);
            currentRow.addView(button, lp);
        }
        if (!sourceStatusOwnedByAction) setSourceStatus(hasMapping ? "Choose a media source" : "Configuration needed");
    }

    private JSONObject sourceAt(int index) { return apiConfigSources == null || index >= apiConfigSources.length() ? null : apiConfigSources.optJSONObject(index); }
    private String lightLabel(String entity, String fallback) {
        if (isOfficeTablet()) {
            if ("switch.modem_power_switch".equals(entity)) return "Desk Lights";
            if ("switch.office_lights_switch_2".equals(entity)) return "Office Lights";
            if ("switch.printer_lights_switch".equals(entity)) return "Printer Lights";
            if ("switch.workbench_switch".equals(entity)) return "Workbench";
            if ("light.office_desk_lights".equals(entity)) return "Desk Over";
            if ("light.office_laser_fan".equals(entity)) return "Laser Fan";
        }
        if (GLOW.equals(entity)) return "Records";
        if (OFFICE.equals(entity)) return "Overhead";
        return fallback;
    }
    private String bedroomLabel(String entity, String fallback) {
        if ("light.bedroom_lamp_light".equals(entity)) return "Bedroom Lamp";
        if ("light.headboard_white_light".equals(entity)) return "Headboard";
        if ("switch.barbecue_lights_switch".equals(entity)) return "Wreath";
        if ("switch.bedroom_fan_switch".equals(entity)) return "Fan";
        if ("switch.bedroom_light".equals(entity)) return "Bedroom Light";
        if ("switch.bedroom_vines_switch".equals(entity)) return "Vines";
        if ("automation.full_bed".equals(entity)) return "Full Bed";
        if ("automation.good_morning1".equals(entity)) return "Good Morning";
        return fallback;
    }
    private IIcon bedroomIcon(String entity) {
        if (entity.contains("fan")) return CommunityMaterial.Icon2.cmd_fan;
        if (entity.contains("lamp")) return CommunityMaterial.Icon2.cmd_lamp;
        if (entity.contains("headboard")) return CommunityMaterial.Icon2.cmd_led_strip;
        if (entity.contains("vines")) return CommunityMaterial.Icon2.cmd_led_strip_variant;
        if (entity.contains("barbecue")) return CommunityMaterial.Icon2.cmd_flower;
        if (entity.contains("automation")) return CommunityMaterial.Icon2.cmd_home_automation;
        if (entity.contains("bedroom_light")) return CommunityMaterial.Icon2.cmd_light_switch;
        return CommunityMaterial.Icon2.cmd_lightbulb;
    }
    private CharSequence iconLabel(IIcon glyph, String label) {
        if (mdiFont == null || glyph == null) return label;
        SpannableString text = new SpannableString(String.valueOf(glyph.getCharacter()) + "\n" + label);
        text.setSpan(new FontSpan(mdiFont), 0, 1, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        return text;
    }
    private IIcon sourceGlyph(String label) {
        String name = label == null ? "" : label.toLowerCase(java.util.Locale.US);
        if (name.contains("wii") || name.contains("xbox") || name.contains("ps2")) return Phosphor.Icon2.pho_game_controller;
        if (name.contains("tv")) return Phosphor.Icon2.pho_monitor;
        if (name.contains("cube")) return Phosphor.Icon.pho_cube;
        if (name.contains("music") || name.contains("record")) return Phosphor.Icon2.pho_music_note;
        return Phosphor.Icon2.pho_game_controller;
    }
    private String sourceMark(String label) {
        String name = label == null ? "" : label.toLowerCase(java.util.Locale.US);
        if (name.contains("wii")) return "Wii";
        if (name.contains("tv")) return "TV";
        if (name.contains("xbox")) return "X";
        if (name.contains("cube")) return "GC";
        if (name.contains("ps2")) return "PS2";
        if (name.contains("record")) return "♫";
        if (name.contains("retropie")) return "RP";
        return "•";
    }
    private boolean validMediaSource(JSONObject source) { String entity = source.optString("entity_id", ""); return validEntity(entity) && entity.startsWith("media_player.") && supports(controls.get(entity), "select_media_source") && !source.optString("source", "").isEmpty(); }
    private void setMedia(int id, boolean enabled) { activity.findViewById(id).setEnabled(enabled); }
    private void styleControlButton(int id) {
        View view = activity.findViewById(id);
        if (view != null) { view.setBackgroundResource(R.drawable.dashboard_control_button); if (view instanceof Button) ((Button) view).setBackgroundTintList(null); }
    }
    private String mediaId() { return mediaControl == null ? "" : mediaControl.optString("entity_id"); }
    private boolean hasConfiguredLightingExceptFan() { for (String id : lightingOrder()) if (!( !isOfficeTablet() && FAN.equals(id)) && controls.containsKey(id) && supports(controls.get(id), "turn_off")) return true; return false; }
    private boolean validEntity(String id) { return id.matches("[a-z_]+\\.[a-z0-9_]+"); }
    private boolean supports(JSONObject c, String action) { if (c == null) return false; JSONArray a = c.optJSONArray("actions"); if (a == null) return false; for (int i = 0; i < a.length(); i++) if (action.equals(a.optString(i))) return true; return false; }
    private String formatTemp(Object v, String unit) { return v == null || v == JSONObject.NULL ? "—" : String.format(java.util.Locale.US, "%s°%s", v, unit); }

    private void changeTemperature(int direction) {
        if (climateControl == null || actionInFlight) return; JSONObject s = states.get(CLIMATE); JSONObject a = s == null ? null : s.optJSONObject("attributes"); if (a == null) return;
        double current = a.optDouble("temperature", Double.NaN), step = a.optDouble("target_temp_step", 1), min = a.optDouble("min_temp", -100), max = a.optDouble("max_temp", 100); if (Double.isNaN(current)) return;
        action(CLIMATE, "set_temperature", value("temperature", Math.max(min, Math.min(max, current + direction * step))));
    }

    private void allOff() {
        if (actionInFlight) return; List<String> targets = new ArrayList<>(); for (String id : lightingOrder()) if (!( !isOfficeTablet() && FAN.equals(id)) && controls.containsKey(id) && supports(controls.get(id), "turn_off")) targets.add(id); if (targets.isEmpty()) return;
        actionInFlight = true; pendingActionId = UUID.randomUUID().toString(); sourceStatusOwnedByAction = true; setSourceStatus("Pending: turning off lighting");
        Log.i("PanelController", "USER_ACTION all_off targets=" + targets);
        executor.execute(() -> { String error = null; try { for (String id : targets) { JSONObject request = new JSONObject(); request.put("entity_id", id); request.put("action", "turn_off"); JSONObject response = api.panelAction(request); Log.i("PanelController", "ACTION_RESULT entity=" + id + " action=turn_off response=" + response); } } catch (Exception e) { error = safePanelError(e); Log.e("PanelController", "ACTION_ERROR all_off=" + error, e); }
            final String result = error; activity.runOnUiThread(() -> { actionInFlight = false; if (result == null) { setSourceStatus("Lighting off; waiting for HA state"); pendingActionId = null; refresh(); } else { setSourceStatus("Action failed: " + result); pendingActionId = null; } }); });
    }

    private void action(String entity, String name, JSONObject args) {
        JSONObject c = controls.get(entity); if (entity == null || entity.isEmpty() || c == null || !supports(c, name) || actionInFlight) return;
        final String requestId = UUID.randomUUID().toString(); pendingActionId = requestId; actionInFlight = true; sourceStatusOwnedByAction = true; setSourceStatus("Pending: " + name);
        Log.i("PanelController", "USER_ACTION id=" + requestId + " entity=" + entity + " action=" + name + " args=" + args);
        executor.execute(() -> { String error = null; try { JSONObject request = new JSONObject(); request.put("entity_id", entity); request.put("action", name); if (args != null) for (java.util.Iterator<String> it = args.keys(); it.hasNext();) { String key = it.next(); request.put(key, args.get(key)); } JSONObject response = api.panelAction(request); Log.i("PanelController", "ACTION_RESULT id=" + requestId + " response=" + response); } catch (Exception e) { error = safePanelError(e); Log.e("PanelController", "ACTION_ERROR id=" + requestId + " error=" + error, e); }
            final String result = error; activity.runOnUiThread(() -> { if (!requestId.equals(pendingActionId)) return; actionInFlight = false; if (result != null) { setSourceStatus("Action failed: " + result); pendingActionId = null; } else { setSourceStatus("Action submitted; waiting for HA state"); pendingActionId = null; refresh(); } }); });
    }

    private void setSourceStatus(String message) { activity.runOnUiThread(() -> ((TextView) activity.findViewById(R.id.source_status)).setText(message)); }
    private void showUnavailable(String message) { ((TextView) activity.findViewById(R.id.lights_state)).setText(message); ((TextView) activity.findViewById(R.id.climate_status)).setText(message); ((TextView) activity.findViewById(R.id.media_detail)).setText(message); setSourceStatus("Panel unavailable"); }
    private static String safePanelError(Exception e) { String m = e.getMessage(); return m != null && m.contains("HTTP") ? m : "Server1 panel unavailable"; }
}
