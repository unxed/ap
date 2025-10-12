// Test for anchor scoping and special characters

const safeConfig = {
    setting: "default" // This should NOT be changed
};

function configure() {
    // Special chars: &*{}[]
    const unsafeConfig = {
        setting: "default" // This one SHOULD be changed
    };
    return unsafeConfig;
}
