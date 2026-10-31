import io.calamares.core

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Rectangle {
    width: parent.width
    height: parent.height
    color: "#2d353b"

    ColumnLayout {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 24
        spacing: 8

        Text {
            Layout.fillWidth: true
            color: "#d3c6aa"
            wrapMode: Text.WordWrap
            text: qsTr("Choose how Ojuny should be installed. The bundled template is prepared for this machine. A prepared ojuny-template repository already contains your configuration; only its hardware module is regenerated.")
        }

        ButtonGroup {
            id: modeGroup
        }

        RadioButton {
            id: bundledButton
            text: qsTr("Use the bundled Ojuny template")
            palette.windowText: "#d3c6aa"
            palette.highlight: "#a7c080"
            palette.highlightedText: "#2d353b"
            ButtonGroup.group: modeGroup
            onCheckedChanged: if (checked) Global.insert("ojuny_template_mode", "bundled")
        }

        RadioButton {
            id: preparedButton
            text: qsTr("Use a prepared ojuny-template repository")
            palette.windowText: "#d3c6aa"
            palette.highlight: "#a7c080"
            palette.highlightedText: "#2d353b"
            ButtonGroup.group: modeGroup
            onCheckedChanged: if (checked) Global.insert("ojuny_template_mode", "prepared")
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 2
            visible: preparedButton.checked

            Label {
                text: qsTr("Repository URL")
                color: "#d3c6aa"
            }

            TextField {
                id: urlField
                Layout.fillWidth: true
                color: "#d3c6aa"
                placeholderTextColor: "#7a8478"
                placeholderText: "https://github.com/you/ojuny-template"
                background: Rectangle {
                    color: "#343f44"
                    border.color: "#475258"
                    radius: 3
                }
                onTextChanged: Global.insert("ojuny_template_url", text)
            }

            Label {
                text: qsTr("Git token")
                color: "#d3c6aa"
            }

            TextField {
                id: tokenField
                Layout.fillWidth: true
                color: "#d3c6aa"
                placeholderTextColor: "#7a8478"
                echoMode: TextInput.Password
                placeholderText: qsTr("Optional, HTTPS only")
                background: Rectangle {
                    color: "#343f44"
                    border.color: "#475258"
                    radius: 3
                }
                onTextChanged: Global.insert("ojuny_template_token", text)
            }

            Label {
                text: qsTr("Branch")
                color: "#d3c6aa"
            }

            TextField {
                id: branchField
                Layout.fillWidth: true
                color: "#d3c6aa"
                placeholderTextColor: "#7a8478"
                placeholderText: qsTr("Optional, defaults to the repository default")
                background: Rectangle {
                    color: "#343f44"
                    border.color: "#475258"
                    radius: 3
                }
                onTextChanged: Global.insert("ojuny_template_branch", text)
            }
        }

        Text {
            Layout.fillWidth: true
            visible: preparedButton.checked
            color: "#d3c6aa"
            wrapMode: Text.WordWrap
            text: qsTr("In prepared mode Ojuny clones the repository, reads the hostname from modules/07-system/00-host.nix, and regenerates only the hardware module. The hostname on the Users page is not used. An HTTPS URL with a token writes ~/.git-credentials with mode 0600; an SSH clone uses your key and gets no credential helper.")
        }
    }

    Component.onCompleted: {
        var savedMode = Global.value("ojuny_template_mode") || "bundled";
        var savedUrl = Global.value("ojuny_template_url") || "";
        var savedToken = Global.value("ojuny_template_token") || "";
        var savedBranch = Global.value("ojuny_template_branch") || "";

        if (!Global.contains("ojuny_template_mode"))
            Global.insert("ojuny_template_mode", savedMode);
        if (!Global.contains("ojuny_template_url"))
            Global.insert("ojuny_template_url", savedUrl);
        if (!Global.contains("ojuny_template_token"))
            Global.insert("ojuny_template_token", savedToken);
        if (!Global.contains("ojuny_template_branch"))
            Global.insert("ojuny_template_branch", savedBranch);

        preparedButton.checked = savedMode === "prepared";
        bundledButton.checked = savedMode !== "prepared";
        urlField.text = savedUrl;
        tokenField.text = savedToken;
        branchField.text = savedBranch;
    }
}
