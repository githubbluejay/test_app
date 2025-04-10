import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import time
from PIL import Image
from io import BytesIO
import base64
import matplotlib.pyplot as plt

# Set page configuration
st.set_page_config(
    page_title="Masters Tournament Leaderboard Tracker",
    page_icon="🏌️‍♂️",
    layout="wide",
)

# Add custom CSS
st.markdown("""
<style>
    .main-title {
        font-size: 42px;
        font-weight: bold;
        color: #006747;  /* Masters green */
        text-align: center;
        margin-bottom: 15px;
    }
    .subtitle {
        font-size: 24px;
        text-align: center;
        color: #333;
        margin-bottom: 30px;
    }
    .stPlotlyChart {
        background-color: #FFFFFF;
        border-radius: 5px;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
    }
    .highlight {
        color: #006747;
        font-weight: bold;
    }
    .player-card {
        border: 1px solid #ddd;
        border-radius: 5px;
        padding: 15px;
        margin: 5px;
        background-color: white;
    }
    .position-1 {
        border-left: 5px solid gold;
    }
    .position-2 {
        border-left: 5px solid silver;
    }
    .position-3 {
        border-left: 5px solid #cd7f32;  /* bronze */
    }
</style>
""", unsafe_allow_html=True)

# Masters Tournament logo (you'd create this or find a suitable image)
def get_masters_logo():
    # Create a simple placeholder "logo" using matplotlib
    fig, ax = plt.subplots(figsize=(2, 1))
    ax.text(0.5, 0.5, 'MASTERS', fontsize=20, fontweight='bold', 
            horizontalalignment='center', verticalalignment='center', color='#006747')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    # Save the figure to a BytesIO object
    buf = BytesIO()
    fig.savefig(buf, format="png", transparent=True, bbox_inches='tight', pad_inches=0)
    plt.close(fig)
    
    # Encode the image to base64
    encoded = base64.b64encode(buf.getvalue()).decode('utf-8')
    
    # Create the HTML img tag
    return f'<img src="data:image/png;base64,{encoded}" style="max-width:100%; height:auto;">'

# Title and description
st.markdown(f"<div class='main-title'>Masters Tournament Leaderboard</div>", unsafe_allow_html=True)
st.markdown(f"<div style='text-align:center;'>{get_masters_logo()}</div>", unsafe_allow_html=True)
st.markdown("<div class='subtitle'>Track player positions across the tournament</div>", unsafe_allow_html=True)

# Load data 
@st.cache_data
def load_data():
    df = pd.read_csv("golf_tournament_data.csv")
    return df

data = load_data()

# Get unique players and rounds
players = data["Short_Name"].unique()
rounds = data["Round"].unique()
max_hole = data["Hole_Number"].max()

# Create sidebar controls
st.sidebar.markdown("## Animation Controls")

# Select players to display (default: top 6 from final leaderboard)
final_data = data[data["Hole_Number"] == max_hole]
top_players = final_data.sort_values("Position").head(6)["Short_Name"].unique()

selected_players = st.sidebar.multiselect(
    "Select players to track",
    options=players,
    default=top_players.tolist()
)

# Speed control
animation_speed = st.sidebar.slider(
    "Animation Speed", 
    min_value=1, 
    max_value=10, 
    value=5,
    help="Control how fast the animation plays (1 = slow, 10 = fast)"
)

# Round selection
selected_round = st.sidebar.radio(
    "Select round to visualize",
    options=["All Rounds"] + [f"Round {r}" for r in rounds]
)

# Type of chart
chart_type = st.sidebar.radio(
    "Select chart type",
    options=["Position Chart (Lower is Better)", "Score Chart (Lower is Better)"]
)

# Button to start animation
start_button = st.sidebar.button("Start Animation")

# Filter data based on selected round
if selected_round != "All Rounds":
    round_num = int(selected_round.split(" ")[1])
    filtered_data = data[data["Round"] == round_num]
    title_prefix = f"Round {round_num}"
    hole_range = range(((round_num-1) * 18) + 1, round_num * 18 + 1)
else:
    filtered_data = data
    title_prefix = "Tournament"
    hole_range = range(1, max_hole + 1)

# Filter for selected players
if selected_players:
    filtered_data = filtered_data[filtered_data["Short_Name"].isin(selected_players)]

# Create main containers
chart_container = st.container()
leaderboard_container = st.container()

# Function to create the animation
def create_animation(data, hole_range, y_column="Position", animate=False):
    # Initialize figure
    fig = go.Figure()
    
    # Prepare data for the plot
    for player in selected_players:
        player_data = data[data["Short_Name"] == player]
        player_full_name = player_data["Full_Name"].iloc[0]
        
        # Get complete trajectory
        trajectory = []
        for hole in hole_range:
            hole_data = player_data[player_data["Hole_Number"] == hole]
            if not hole_data.empty:
                trajectory.append({
                    "Hole": hole,
                    y_column: hole_data[y_column].iloc[0]
                })
        
        # Convert to dataframe
        trajectory_df = pd.DataFrame(trajectory)
        
        # Add trace for this player
        fig.add_trace(
            go.Scatter(
                x=trajectory_df["Hole"],
                y=trajectory_df[y_column],
                mode="lines+markers",
                name=f"{player} ({player_full_name})",
                line=dict(width=3),
                marker=dict(size=8)
            )
        )
    
    # Set axis properties
    hole_names = []
    for hole in hole_range:
        round_num = (hole - 1) // 18 + 1
        hole_in_round = ((hole - 1) % 18) + 1
        if hole_in_round == 1:
            hole_names.append(f"R{round_num} H{hole_in_round}")
        elif hole_in_round % 3 == 0:  # Label every 3rd hole
            hole_names.append(f"H{hole_in_round}")
        else:
            hole_names.append("")
            
    # Configure the layout
    title = f"{title_prefix} {'Leaderboard Positions' if y_column=='Position' else 'Scores'} Over Time"
    
    fig.update_layout(
        title=dict(
            text=title,
            font=dict(size=24)
        ),
        xaxis=dict(
            title="Hole",
            tickvals=list(hole_range),
            ticktext=hole_names,
            tickangle=45,
            gridcolor='lightgray'
        ),
        yaxis=dict(
            title="Position" if y_column=="Position" else "Score to Par",
            gridcolor='lightgray',
            autorange="reversed" if y_column=="Position" else None,
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        plot_bgcolor='white',
        hovermode='x unified',
        height=600,
        margin=dict(l=60, r=30, t=80, b=60)
    )
    
    # Add vertical lines to separate rounds
    for r in range(1, 5):
        fig.add_vline(
            x=(r-1)*18 + 0.5,  # Add line before first hole of each round
            line_width=1, 
            line_dash="dash", 
            line_color="gray",
            annotation_text=f"Round {r}" if r > 1 else None,
            annotation_position="top left"
        )
    
    # Create animation frames if requested
    if animate:
        frames = []
        for i, hole in enumerate(hole_range):
            frame_data = []
            
            for player in selected_players:
                player_data = data[data["Short_Name"] == player]
                player_trajectory = []
                
                # Get data up to current hole
                for h in range(min(hole_range), hole + 1):
                    hole_data = player_data[player_data["Hole_Number"] == h]
                    if not hole_data.empty:
                        player_trajectory.append({
                            "Hole": h,
                            y_column: hole_data[y_column].iloc[0]
                        })
                
                trajectory_df = pd.DataFrame(player_trajectory) if player_trajectory else pd.DataFrame({"Hole": [], y_column: []})
                
                frame_data.append(
                    go.Scatter(
                        x=trajectory_df["Hole"],
                        y=trajectory_df[y_column]
                    )
                )
            
            frames.append(go.Frame(data=frame_data, name=f"hole_{hole}"))
        
        # Add frames to figure
        fig.frames = frames
        
        # Add play button
        fig.update_layout(
            updatemenus=[{
                "type": "buttons",
                "buttons": [
                    {
                        "label": "Play",
                        "method": "animate",
                        "args": [
                            None, 
                            {
                                "frame": {"duration": 400 / animation_speed, "redraw": True},
                                "fromcurrent": True,
                                "transition": {"duration": 300 / animation_speed}
                            }
                        ]
                    }
                ],
                "direction": "left",
                "showactive": False,
                "x": 0.1,
                "y": 0,
                "xanchor": "right",
                "yanchor": "bottom"
            }]
        )
    
    return fig

# Create and display the animation
with chart_container:
    # Show entire chart if no animation requested
    if chart_type == "Position Chart (Lower is Better)":
        y_column = "Position"
    else:  # Score Chart
        y_column = "Total_Score"
    
    # Create and display the chart
    fig = create_animation(filtered_data, hole_range, y_column, animate=start_button)
    st.plotly_chart(fig, use_container_width=True)

# Display current leaderboard
with leaderboard_container:
    st.markdown("### Current Leaderboard")
    
    # Determine which hole to show based on animation state
    if start_button:
        # For animation, this would be determined by the animation state
        # Here we'll just show the final leaderboard
        last_hole = max(hole_range)
    else:
        last_hole = max(hole_range)
    
    # Get data for the selected hole
    hole_data = data[data["Hole_Number"] == last_hole]
    
    # Sort by position
    leaderboard = hole_data.sort_values("Position")[["Short_Name", "Full_Name", "Position", "Total_Score"]]
    
    # Display in a grid of cards
    cols = st.columns(4)
    for i, (_, player) in enumerate(leaderboard.head(8).iterrows()):
        with cols[i % 4]:
            position_class = f"position-{int(player['Position'])}" if player["Position"] <= 3 else ""
            st.markdown(f"""
            <div class="player-card {position_class}">
                <h4>{int(player['Position'])}. {player['Short_Name']}</h4>
                <p>{player['Full_Name']}</p>
                <p><span class="highlight">{player['Total_Score']}</span></p>
            </div>
            """, unsafe_allow_html=True)

# Footer
st.markdown("---")
st.markdown("Made with ❤️ using Streamlit and Plotly") 