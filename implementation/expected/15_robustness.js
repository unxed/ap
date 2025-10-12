// Test for anchor scoping and special characters

const safeConfig = {
    setting: "default" // This should NOT be changed
};

function configure() {
    // All special characters handled correctly
    const unsafeConfig = {
        setting: "overridden" // Changed safely within anchor
    };
    return unsafeConfig;
}
