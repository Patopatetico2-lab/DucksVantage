import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.plasma5support as Plasma5Support

PlasmoidItem {
    id: root

    property string modelName: "Lenovo"
    property string activeProfile: "balanced"
    property real cpuTemp: 0
    property real gpuTemp: 0
    property bool gpuAvailable: false
    property string gpuState: "D3cold"
    property int batPercent: 0
    property bool batAc: true
    property int currentHz: 60
    property bool ecoActive: false
    property bool cinemaActive: false

    readonly property bool vertical: Plasmoid.formFactor === PlasmaCore.Types.Vertical

    function profileShort(prof) {
        if (prof === "max-power") return "MAX"
        if (prof === "performance") return "PERF"
        if (prof === "low-power" || prof === "quiet") return "SIL"
        if (prof === "custom") return "CUST"
        return "BAL"
    }

    function profileColor(prof) {
        if (prof === "max-power") return "#60a5fa"
        if (prof === "performance") return "#f59e0b"
        if (prof === "low-power" || prof === "quiet") return "#34d399"
        if (prof === "custom") return "#a78bfa"
        return "#94a3b8"
    }

    function runDv(args) {
        var cmd = "ducksvantage " + args
        execAction.connectSource(cmd)
        refreshTimer.restart()
    }

    Plasmoid.backgroundHints: PlasmaCore.Types.DefaultBackground | PlasmaCore.Types.ConfigurableBackground
    toolTipMainText: "Ducksvantage • " + modelName
    toolTipSubText: "Perfil: " + activeProfile.toUpperCase()
        + " | CPU: " + Math.round(cpuTemp) + "°C"
        + (gpuAvailable ? (" | GPU: " + Math.round(gpuTemp) + "°C") : (" | GPU: " + gpuState))
        + " | Bateria: " + batPercent + "% (" + (batAc ? "AC" : "BAT") + ")"

    Plasma5Support.DataSource {
        id: execPoll
        engine: "executable"
        connectedSources: []
        onNewData: function(sourceName, data) {
            if (data["stdout"]) {
                try {
                    var obj = JSON.parse(data["stdout"])
                    root.modelName = obj.model || "Lenovo"
                    root.activeProfile = obj.profile || "balanced"
                    root.ecoActive = !!obj.eco_mode
                    root.cinemaActive = !!obj.cinema_mode
                    if (obj.cpu) root.cpuTemp = obj.cpu.temp_c || 0
                    if (obj.gpu) {
                        root.gpuAvailable = !!obj.gpu.available
                        root.gpuTemp = obj.gpu.temp_c || 0
                        root.gpuState = obj.gpu.state || "D3cold"
                    }
                    if (obj.battery) {
                        root.batPercent = obj.battery.percent || 0
                        root.batAc = !!obj.battery.ac
                    }
                    if (obj.display) {
                        root.currentHz = obj.display.hz || 60
                    }
                } catch (e) {}
            }
            execPoll.disconnectSource(sourceName)
        }
    }

    Plasma5Support.DataSource {
        id: execAction
        engine: "executable"
        connectedSources: []
        onNewData: function(sourceName, _data) {
            execAction.disconnectSource(sourceName)
            execPoll.connectSource("ducksvantage --status --json")
        }
    }

    Timer {
        id: refreshTimer
        interval: 3000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: execPoll.connectSource("ducksvantage --status --json")
    }

    compactRepresentation: MouseArea {
        Layout.minimumWidth: root.vertical ? Kirigami.Units.iconSizes.medium : rowLayout.implicitWidth + Kirigami.Units.smallSpacing * 2
        Layout.minimumHeight: Kirigami.Units.iconSizes.smallMedium
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton
        onClicked: function(mouse) {
            if (mouse.button === Qt.MiddleButton) {
                root.runDv("--cycle-profile --json")
            } else {
                root.expanded = !root.expanded
            }
        }

        RowLayout {
            id: rowLayout
            anchors.centerIn: parent
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: "ducksvantage"
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            }

            PlasmaComponents3.Label {
                text: Math.round(root.cpuTemp) + "°" + (root.gpuAvailable ? ("/" + Math.round(root.gpuTemp) + "°") : "")
                font.bold: true
                font.pixelSize: Math.round(Kirigami.Theme.defaultFont.pixelSize * 0.92)
            }

            Rectangle {
                visible: !root.vertical
                color: "#1c1e22"
                border.color: root.profileColor(root.activeProfile)
                border.width: 1
                radius: 4
                Layout.preferredWidth: badgeLbl.implicitWidth + 8
                Layout.preferredHeight: badgeLbl.implicitHeight + 4

                PlasmaComponents3.Label {
                    id: badgeLbl
                    anchors.centerIn: parent
                    text: root.profileShort(root.activeProfile)
                    color: root.profileColor(root.activeProfile)
                    font.bold: true
                    font.pixelSize: Math.round(Kirigami.Theme.smallFont.pixelSize * 0.92)
                }
            }
        }
    }

    fullRepresentation: ColumnLayout {
        Layout.preferredWidth: Kirigami.Units.gridUnit * 18
        Layout.minimumWidth: Kirigami.Units.gridUnit * 15
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true
            Kirigami.Heading {
                level: 4
                text: "Ducksvantage • " + root.modelName
                Layout.fillWidth: true
            }
            PlasmaComponents3.Label {
                text: root.profileShort(root.activeProfile)
                font.bold: true
                color: root.profileColor(root.activeProfile)
            }
        }

        PlasmaComponents3.Label {
            Layout.fillWidth: true
            text: "CPU: " + Math.round(root.cpuTemp) + "°C   |   GPU: "
                + (root.gpuAvailable ? (Math.round(root.gpuTemp) + "°C") : root.gpuState)
                + "   |   Tela: " + root.currentHz + " Hz"
            opacity: 0.85
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 2
            rowSpacing: 4
            columnSpacing: 4

            PlasmaComponents3.Button {
                Layout.fillWidth: true
                text: "Silencioso"
                checkable: true
                checked: root.activeProfile === "low-power" || root.activeProfile === "quiet"
                onClicked: root.runDv("--profile low-power")
            }
            PlasmaComponents3.Button {
                Layout.fillWidth: true
                text: "Equilibrado"
                checkable: true
                checked: root.activeProfile === "balanced"
                onClicked: root.runDv("--profile balanced")
            }
            PlasmaComponents3.Button {
                Layout.fillWidth: true
                text: "Desempenho"
                checkable: true
                checked: root.activeProfile === "performance"
                onClicked: root.runDv("--profile performance")
            }
            PlasmaComponents3.Button {
                Layout.fillWidth: true
                text: "Max-Power"
                checkable: true
                checked: root.activeProfile === "max-power"
                onClicked: root.runDv("--profile max-power")
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 4

            PlasmaComponents3.Button {
                Layout.fillWidth: true
                text: "Alternar Hz (" + root.currentHz + ")"
                onClicked: root.runDv("--cycle-hz --json")
            }
            PlasmaComponents3.Button {
                Layout.fillWidth: true
                text: root.ecoActive ? "Eco: ON" : "Eco-Mode"
                checkable: true
                checked: root.ecoActive
                onClicked: root.runDv("--eco toggle")
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 4

            PlasmaComponents3.Button {
                Layout.fillWidth: true
                text: root.cinemaActive ? "Cinema: ON" : "Modo Cinema"
                checkable: true
                checked: root.cinemaActive
                onClicked: root.runDv("--cinema toggle")
            }
            PlasmaComponents3.Button {
                Layout.fillWidth: true
                text: "Abrir Painel"
                icon.name: "configure"
                onClicked: {
                    execAction.connectSource("nohup ducksvantage >/dev/null 2>&1 &")
                    root.expanded = false
                }
            }
        }
    }
}
